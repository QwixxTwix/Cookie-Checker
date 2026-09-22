# config.py — by Qwixx

import json
import os

CONFIG_FILENAME = "config.json"

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) "
    "Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
    "Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:122.0) "
    "Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]

# Все доступные категории сервисов (для only_categories)
CATEGORIES = [
    "finance", "social", "email", "gaming", "streaming",
    "marketplace", "productivity", "cloud", "network", "database",
]

DEFAULT_CONFIG = {
    # ─── Производительность ────────────────────────────────
    "workers": 4,
    "timeout": 15,
    "max_retries": 2,

    # ─── User-Agent ────────────────────────────────────────
    "user_agent": UA_POOL[0],
    "user_agents": UA_POOL,
    "rotate_ua": True,

    # ─── Прокси ────────────────────────────────────────────
    "proxy": None,
    "proxies": [],
    "rotate_proxy": True,
    "proxy_check_on_start": True,
    "proxy_check_workers": 10,

    # ─── Rate limit (запросов в секунду на хост) ───────────
    "rate_limit": {
        "default": 5,
        "steamcommunity.com": 3,
        "users.roblox.com": 5,
        "www.netflix.com": 2,
        "api.twitch.tv": 8,
        "api.twitter.com": 3,
        "graph.facebook.com": 3,
        "discord.com": 5,
        "www.binance.com": 5,
        "auth.riotgames.com": 3,
        "www.reddit.com": 3,
        "pro.kraken.com": 3,
        "www.amazon.com": 3,
        "www.tiktok.com": 3,
    },

    # ─── Вывод / экспорт ───────────────────────────────────
    "output_file": "valid_cookies.txt",
    "output_format": "jsonl",   # jsonl | json | csv | txt
    "only_valid": False,
    "no_save": False,
    "deduplicate": True,
    "retry_network": True,

    # ─── Логи ──────────────────────────────────────────────
    "log_file": "",
    "log_level": "INFO",        # DEBUG | INFO | WARNING | ERROR
    "log_max_bytes": 0,         # 0 = без ротации
    "log_backup_count": 3,

    # ─── Вебхуки ───────────────────────────────────────────
    "webhooks": {
        "enabled": False,
        "async": True,
        "dedup": True,

        # Уровень: "all" (все валидные) | "premium" (только с
        # премиум-полями: email/phone/balance/nitro/robux/...)
        "min_level": "all",

        # Ограничение по конкретным сервисам (пусто = все)
        "only_services": [],

        # Ограничение по категориям (пусто = все).
        # Доступные: finance, social, email, gaming, streaming,
        #            marketplace, productivity, cloud, network, database
        "only_categories": [],

        # Минимум доп. полей в info, чтобы отправить (0 = без порога)
        "min_info_fields": 0,

        # Шаблон для generic (пусто = DEFAULT_TEMPLATE из webhooks.py).
        # Плейсхолдеры: {service} {cookie_masked} {fields} {emoji}
        #               {category} {field:имя_поля}
        "template": "",

        # ── Discord ────────────────────────────────────────
        "discord": {
            "url": "",
            "username": "Cookie Checker",
            "avatar_url": "",
            "mention_role_id": "",       # ID роли для пинга (или "")
            "ping_on_valid": True,       # пинговать роль
            "show_category": True,       # показывать категорию в footer
        },

        # ── Telegram ───────────────────────────────────────
        "telegram": {
            "token": "",
            "chat_id": "",
            "silent": False,             # без звука
            "disable_preview": True,     # без превью ссылок
            "with_button": True,         # кнопка «Профиль»
        },

        # ── Slack ──────────────────────────────────────────
        "slack": {
            "url": "",
            "channel": "",
            "username": "Cookie Checker",
        },

        # ── Generic (любой URL) ────────────────────────────
        "generic": {
            "url": "",
            "method": "POST",
            "headers": {},
            "include_info": True,        # вкладывать info в payload
        },
    },
}


def _deep_merge(base, override):
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _deep_clean(cfg, template):
    out = {}
    for k, v in template.items():
        if k not in cfg:
            out[k] = v
            continue
        cv = cfg[k]
        if isinstance(v, dict) and isinstance(cv, dict):
            out[k] = _deep_clean(cv, v)
        else:
            out[k] = cv
    return out


def load_config(path=None):
    cfg = dict(DEFAULT_CONFIG)
    path = path or CONFIG_FILENAME
    if not os.path.isfile(path):
        return cfg

    try:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
    except Exception as e:
        print(f"[config] не удалось прочитать {path}: {e}")
        return cfg

    if isinstance(user, dict):
        cfg = _deep_merge(cfg, user)
    return cfg


def save_config(cfg, path=None):
    path = path or CONFIG_FILENAME
    clean = _deep_clean(cfg, DEFAULT_CONFIG)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[config] не удалось сохранить {path}: {e}")
        return False


def is_webhook_ready(cfg):
    wh = (cfg or {}).get("webhooks") or {}
    if not wh.get("enabled"):
        return False

    d = wh.get("discord") or {}
    t = wh.get("telegram") or {}
    s = wh.get("slack") or {}
    g = wh.get("generic") or {}

    if d.get("url"):
        return True
    if t.get("token") and t.get("chat_id"):
        return True
    if s.get("url"):
        return True
    if g.get("url"):
        return True
    return False