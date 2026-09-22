# proxy_checker.py — by idqwixxa

import concurrent.futures

import requests

from utils import log

DEFAULT_CHECK_URL = "https://httpbin.org/ip"
DEFAULT_TIMEOUT = 8
DEFAULT_WORKERS = 10


def _label(proxy):
    if not isinstance(proxy, dict):
        return str(proxy)[:60]
    url = proxy.get("https") or proxy.get("http") or ""
    if "@" in url:
        scheme, rest = url.split("://", 1) if "://" in url else ("", url)
        creds, host = rest.rsplit("@", 1)
        user = creds.split(":")[0]
        return f"{scheme}://{user}:***@{host}"
    return url or str(proxy)[:60]


def check_proxy(proxy, url=DEFAULT_CHECK_URL, timeout=DEFAULT_TIMEOUT):
    if not isinstance(proxy, dict):
        return False, "invalid proxy type (not dict)"
    try:
        r = requests.get(url, proxies=proxy, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 (ProxyCheck)"})
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        try:
            data = r.json()
            ip = data.get("origin") or data.get("ip") or "?"
        except Exception:
            ip = (r.text or "").strip()[:60] or "?"
        return True, ip
    except requests.exceptions.ProxyError as e:
        return False, f"proxy error: {str(e)[:80]}"
    except requests.exceptions.ConnectTimeout:
        return False, "connect timeout"
    except requests.exceptions.ReadTimeout:
        return False, "read timeout"
    except requests.exceptions.SSLError:
        return False, "ssl error"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:80]}"


def filter_alive(proxies, workers=DEFAULT_WORKERS, url=DEFAULT_CHECK_URL,
                 timeout=DEFAULT_TIMEOUT):
    if not proxies:
        return []

    proxies = [p for p in proxies if isinstance(p, dict)]
    if not proxies:
        log.warning("proxy filter: список пуст или невалиден")
        return []

    workers = max(1, min(int(workers), len(proxies)))
    log.info(f"proxy check: {len(proxies)} шт, workers={workers}")

    alive = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(check_proxy, p, url, timeout): p for p in proxies}
        for fut in concurrent.futures.as_completed(futures):
            p = futures[fut]
            try:
                ok, info = fut.result()
            except Exception as e:
                ok, info = False, f"{type(e).__name__}: {e}"
            if ok:
                alive.append(p)
                log.info(f"  proxy OK   {_label(p)}  →  {info}")
            else:
                log.warning(f"  proxy DEAD {_label(p)}  →  {info}")

    log.info(f"proxy check done: {len(alive)}/{len(proxies)} alive")
    return alive