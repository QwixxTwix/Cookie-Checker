# utils.py — by Qwixx

import os
import re
import csv
import gzip
import json
import logging
import tempfile
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from colorama import Fore, Style, init

init(autoreset=True)

R = Fore.RED
G = Fore.GREEN
Y = Fore.YELLOW
C = Fore.CYAN
M = Fore.MAGENTA
W = Fore.WHITE
B = Style.BRIGHT
DIM = Style.DIM
RST = Style.RESET_ALL

VALID_FILE = "valid_cookies.txt"

_write_lock = threading.Lock()
_log_lock = threading.Lock()

log = logging.getLogger("checker")
log.setLevel(logging.INFO)
log.propagate = False
_log_configured = False

# ── Мини-карта категорий (чтобы не тянуть webhooks сюда) ──────
_CATEGORY_EMOJI = {
    "binance": "💰", "coinbase": "💰", "paypal": "💰",
    "stripe": "💰", "kraken": "💰", "metamask": "💰",
    "trustwallet": "💰", "opensea": "💰",

    "telegram": "💬", "instagram": "💬", "facebook": "💬",
    "vk": "💬", "whatsapp": "💬", "discord": "💬",
    "twitter": "💬", "reddit": "💬", "linkedin": "💬",
    "tiktok": "💬", "twitch": "💬",

    "proton": "📧", "yahoo": "📧", "mailru": "📧",
    "google": "📧", "microsoft365": "📧",

    "steam": "🎮", "epic": "🎮", "riot": "🎮",
    "battlenet": "🎮", "xbox": "🎮", "roblox": "🎮",

    "netflix": "📺", "spotify": "📺",

    "amazon": "🛒", "ebay": "🛒", "airbnb": "🛒",

    "slack": "📊", "jira": "📊", "notion": "📊",
    "trello": "📊", "dropbox": "📊",
    "github": "📊", "gitlab": "📊", "bitbucket": "📊",

    "aws": "☁️", "azure": "☁️", "digitalocean": "☁️",
    "cloudflare": "☁️",

    "openvpn": "🔒", "wireguard": "🔒",

    "adminer": "🗄️", "phpmyadmin": "🗄️",
}


def _emoji(service):
    if not service:
        return "✨"
    return _CATEGORY_EMOJI.get(str(service).lower(), "✨")


class _ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": f"{DIM}{C}",
        "INFO": f"{C}",
        "WARNING": f"{Y}",
        "ERROR": f"{R}",
        "CRITICAL": f"{B}{R}",
    }

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        msg = record.getMessage()
        return f"{DIM}{ts}{RST} {color}[{record.levelname[0]}]{RST} {msg}"


class _PlainFormatter(logging.Formatter):
    def format(self, record):
        ts = datetime.fromtimestamp(record.created).strftime(
            "%Y-%m-%d %H:%M:%S")
        return f"{ts} [{record.levelname:<8}] {record.getMessage()}"


def setup_logger(log_file="", level="INFO", max_bytes=0, backup_count=3):
    global _log_configured

    try:
        log.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    except Exception:
        log.setLevel(logging.INFO)

    for h in list(log.handlers):
        try:
            log.removeHandler(h)
        except Exception:
            pass

    sh = logging.StreamHandler()
    sh.setFormatter(_ColorFormatter())
    log.addHandler(sh)

    if log_file:
        try:
            d = os.path.dirname(os.path.abspath(log_file))
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)

            if max_bytes and max_bytes > 0:
                fh = RotatingFileHandler(
                    log_file, maxBytes=int(max_bytes),
                    backupCount=int(backup_count) or 3,
                    encoding="utf-8",
                )
            else:
                fh = logging.FileHandler(log_file, encoding="utf-8")

            fh.setFormatter(_PlainFormatter())
            log.addHandler(fh)
        except Exception as e:
            log.warning(f"Не удалось открыть лог-файл {log_file}: {e}")

    _log_configured = True


def _ensure_logger():
    if not _log_configured:
        setup_logger()


def log_result(service, raw, info):
    """Красивый лог результата с эмодзи категории."""
    _ensure_logger()
    masked = mask_cookie(raw)

    if info and info.get("valid"):
        emoji = _emoji(service)
        log.info(f"{emoji} {B}{service}{RST} {G}VALID{RST}  {masked}")
    elif info is None:
        log.debug(f"{service} EMPTY  {masked}")
    else:
        err = info.get("error", "invalid")
        code = info.get("code", "")
        tag = f" ({code})" if code else ""
        log.debug(f"{service} INVALID {masked} → {err}{tag}")


_CTRL_RX = re.compile(r"[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]")


def sanitize_for_log(s, max_len=500):
    if s is None:
        return ""
    s = str(s)
    s = _CTRL_RX.sub("", s)
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    if max_len and len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def _from_json_list(data):
    jar = {}
    for c in data:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if not name:
            continue
        val = c.get("value", "")
        if val is None:
            val = ""
        jar[str(name)] = str(val)
    return jar


def _from_json_obj(data):
    if all(isinstance(v, (str, int, float, bool)) or v is None
           for v in data.values()):
        return {str(k): ("" if v is None else str(v)) for k, v in data.items()}

    jar = {}
    for k, v in data.items():
        if isinstance(v, dict) and "value" in v:
            jar[str(k)] = str(v.get("value") or "")
        elif isinstance(v, (str, int, float, bool)):
            jar[str(k)] = str(v)
    return jar


def _from_netscape(raw):
    jar = {}
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split("\t")
        if len(parts) >= 7:
            jar[parts[5]] = parts[6]
    return jar


def _from_pairs(raw):
    jar = {}
    if "=" not in raw:
        return jar
    for item in raw.split(";"):
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        k = k.strip()
        if not k:
            continue
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        jar[k] = v
    return jar


def parse_cookies(raw):
    raw = (raw or "").strip()
    if not raw:
        return {}

    if raw[:1] in "[{":
        try:
            data = json.loads(raw)
        except Exception:
            data = None
        if isinstance(data, list):
            jar = _from_json_list(data)
            if jar:
                return jar
        elif isinstance(data, dict):
            jar = _from_json_obj(data)
            if jar:
                return jar

    if ";" not in raw and "\t" in raw:
        for line in raw.splitlines():
            if line.count("\t") >= 6:
                jar = _from_netscape(raw)
                if jar:
                    return jar
                break

    return _from_pairs(raw)


def cookies_to_str(jar):
    if not jar:
        return ""
    return "; ".join(f"{k}={v}" for k, v in sorted(jar.items()))


_JWT_RX = re.compile(
    r"^[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}$")


def _mask_single_token(tok):
    n = len(tok)
    if n <= 24:
        return tok
    if _JWT_RX.match(tok):
        parts = tok.split(".")
        head = parts[0][:10]
        tail = parts[-1][-6:] if len(parts[-1]) >= 6 else parts[-1]
        return f"{head}…{tail} (JWT, {n} ch)"
    return f"{tok[:16]}…{tok[-6:]} ({n} ch)"


def mask_cookie(raw, service=None):
    raw = (raw or "").replace("\n", " ").strip()
    if not raw:
        return "—"

    if "=" in raw and ";" in raw:
        jar = _from_pairs(raw)
        if jar:
            parts = []
            for k, v in jar.items():
                if not v:
                    parts.append(f"{k}=")
                    continue
                if len(v) <= 8:
                    parts.append(f"{k}={v}")
                else:
                    parts.append(f"{k}={v[:4]}…{v[-3:]}")
            s = "; ".join(parts)
            if len(s) > 120:
                s = s[:117] + "…"
            return s

    if "=" not in raw:
        return _mask_single_token(raw)

    k, _, v = raw.partition("=")
    k = k.strip()
    v = v.strip()
    if not v:
        return f"{k}="
    if len(v) <= 10:
        return f"{k}={v}"
    return f"{k}={v[:5]}…{v[-4:]} ({len(v)} ch)"


def load_file(path):
    if not os.path.isfile(path):
        return []

    opener = gzip.open if path.lower().endswith(".gz") else open
    encodings = ("utf-8-sig", "utf-8", "cp1251", "latin-1")

    for enc in encodings:
        try:
            with opener(path, "rt", encoding=enc, errors="strict") as f:
                return [
                    ln.strip() for ln in f
                    if ln.strip() and not ln.lstrip().startswith("#")
                ]
        except UnicodeDecodeError:
            continue
        except Exception:
            return []
    return []


def _atomic_write_text(path, data):
    d = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass
        raise


def save_result(entry, path=VALID_FILE, append=True):
    try:
        entry = dict(entry)
        entry.setdefault(
            "checked_at",
            datetime.now(timezone.utc)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z"),
        )
        line = json.dumps(entry, ensure_ascii=False) + "\n"

        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)

        with _write_lock:
            if append:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
            else:
                _atomic_write_text(path, line)
    except Exception as e:
        _ensure_logger()
        log.warning(f"save_result fail: {e}")


def fmt_value(v):
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "YES" if v else "no"
    if isinstance(v, (list, tuple, set)):
        v = ", ".join(str(x) for x in v)
    if isinstance(v, dict):
        try:
            v = json.dumps(v, ensure_ascii=False)
        except Exception:
            v = str(v)
    if isinstance(v, float):
        v = f"{v:g}"
    if isinstance(v, datetime):
        try:
            v = v.astimezone(timezone.utc).isoformat(timespec="seconds")
        except Exception:
            v = str(v)

    s = str(v)
    if len(s) > 140:
        s = s[:140] + "…"
    return s


def export_results(entries, path, fmt="jsonl", append=False, only_valid=False):
    if not entries:
        return False

    if only_valid:
        entries = [e for e in entries if (e.get("info") or {}).get("valid")]
        if not entries:
            return False

    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            return False

    try:
        if fmt == "jsonl":
            with open(path, "a", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            return True

        if fmt == "json":
            if append and os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    if not isinstance(existing, list):
                        existing = []
                except Exception:
                    existing = []
                existing.extend(entries)
                data = json.dumps(existing, indent=2, ensure_ascii=False)
            else:
                data = json.dumps(entries, indent=2, ensure_ascii=False)
            _atomic_write_text(path, data)
            return True

        if fmt == "csv":
            info_keys = set()
            for e in entries:
                info_keys.update((e.get("info") or {}).keys())
            info_keys = sorted(info_keys)
            cols = ["service", "checked_at", "cookie"] + info_keys

            write_header = True
            if append and os.path.isfile(path) and os.path.getsize(path) > 0:
                write_header = False

            if append:
                f = open(path, "a", encoding="utf-8", newline="")
            else:
                tmp_path = path + ".tmp"
                f = open(tmp_path, "w", encoding="utf-8", newline="")

            try:
                wr = csv.writer(f)
                if write_header:
                    wr.writerow(cols)
                for e in entries:
                    info = e.get("info") or {}
                    row = [e.get("service", ""),
                           e.get("checked_at", ""),
                           e.get("cookie", "")]
                    row += [fmt_value(info.get(k, "")) for k in info_keys]
                    wr.writerow(row)
            finally:
                f.close()

            if not append:
                os.replace(tmp_path, path)
            return True

        if fmt == "txt":
            mode = "a" if append else "w"
            with open(path, mode, encoding="utf-8") as f:
                for e in entries:
                    f.write(f"{e.get('cookie', '')}\n")
            return True

    except Exception as e:
        _ensure_logger()
        log.warning(f"export_results fail: {e}")
        return False

    return False


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def sep(char="─", length=60, color=M):
    return f"{DIM}{color}{char * length}{RST}"


class Stats:
    def __init__(self):
        self.total = 0
        self.valid = 0
        self.invalid = 0
        self.unknown = 0
        self.duplicate = 0
        self.per_service = {}
        self.per_category = {}
        self._lock = threading.Lock()

    def add(self, kind, service=None, category=None):
        with self._lock:
            self.total += 1
            if kind == "valid":
                self.valid += 1
            elif kind == "invalid":
                self.invalid += 1
            elif kind == "unknown":
                self.unknown += 1
            elif kind in ("dup", "duplicate"):
                self.duplicate += 1

            if service:
                b = self.per_service.setdefault(
                    service, {"valid": 0, "invalid": 0, "unknown": 0})
                b[kind] = b.get(kind, 0) + 1

            if category:
                self.per_category[category] = (
                    self.per_category.get(category, 0) + 1)

    def reset(self):
        with self._lock:
            self.total = 0
            self.valid = 0
            self.invalid = 0
            self.unknown = 0
            self.duplicate = 0
            self.per_service.clear()
            self.per_category.clear()

    def snapshot(self):
        with self._lock:
            return {
                "total": self.total,
                "valid": self.valid,
                "invalid": self.invalid,
                "unknown": self.unknown,
                "duplicate": self.duplicate,
                "per_service": {k: dict(v)
                                for k, v in self.per_service.items()},
                "per_category": dict(self.per_category),
            }