# main.py — by Qwixx

import argparse
import hashlib
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils import (
    R, G, Y, C, M, W, B, DIM, RST,
    clear, parse_cookies, mask_cookie, load_file,
    fmt_value, save_result, export_results, setup_logger, log,
    sanitize_for_log, Stats,
)
from services import detect_service, SERVICES
from checkers import (
    run_check_logged, configure as configure_checkers,
    set_webhook_manager,
)
from config import load_config, save_config, DEFAULT_CONFIG, is_webhook_ready
from webhooks import (
    build_from_config as build_webhooks,
    _categorize,
    CATEGORIES as CATEGORY_META,
)

VERSION = "v1.0"

BANNER = f"""{B}{M}
 ██████╗ ██████╗  ██████╗ ██╗  ██╗██╗███████╗
██╔════╝██╔═══██╗██╔═══██╗██║ ██╔╝██║██╔════╝
██║     ██║   ██║██║   ██║█████╔╝ ██║█████╗
██║     ██║   ██║██║   ██║██╔═██╗ ██║██╔══╝
╚██████╗╚██████╔╝╚██████╔╝██║  ██╗██║███████╗
 ╚═════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝╚══════╝
{RST}{B}{C}       Universal  Cookie  Checker{RST}
{B}{G}             by Qwixx  ·  {VERSION}{RST}
"""

CFG = dict(DEFAULT_CONFIG)

stats = Stats()

_print_lock = threading.Lock()
_collected = []
_collected_lock = threading.Lock()

_seen_lock = threading.Lock()
_seen_hashes = set()

_retry_lock = threading.Lock()
_retry_items = []

_webhook_mgr = None

_last_progress = [0, 0]
_progress_lock = threading.Lock()
_use_live_progress = True


# ─────────────────────────────────────────────────────────────
# ПРОГРЕСС-БАР
# ─────────────────────────────────────────────────────────────

def _progress_bar(done, total, width=28, valid=0, invalid=0,
                  unknown=0, dup=0):
    if total <= 0:
        return ""
    frac = done / total
    filled = int(width * frac)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(frac * 100)
    return (f"{C}{bar}{RST} {B}{pct:3d}%{RST} "
            f"{DIM}({done}/{total}){RST}  "
            f"{G}✓{valid}{RST} {R}✗{invalid}{RST} "
            f"{Y}?{unknown}{RST} {DIM}~{dup}{RST}")


def _draw_progress(done, total, force=False):
    if not _use_live_progress:
        return
    s = stats.snapshot()
    line = _progress_bar(done, total, valid=s["valid"],
                         invalid=s["invalid"], unknown=s["unknown"],
                         dup=s["duplicate"])
    try:
        sys.stdout.write("\r" + line + "  ")
        sys.stdout.flush()
    except Exception:
        pass


def _clear_progress():
    if not _use_live_progress:
        return
    try:
        sys.stdout.write("\r" + " " * 140 + "\r")
        sys.stdout.flush()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# РЕНДЕР РЕЗУЛЬТАТА
# ─────────────────────────────────────────────────────────────

def _stats_report() -> str:
    s = stats.snapshot()
    parts = [
        f"{C}Всего:{RST} {B}{s['total']}{RST}",
        f"{G}Валид:{RST} {B}{s['valid']}{RST}",
        f"{R}Невалид:{RST} {B}{s['invalid']}{RST}",
        f"{Y}Неизвестно:{RST} {B}{s['unknown']}{RST}",
        f"{DIM}Дубли:{RST} {s['duplicate']}",
    ]
    return f"{B}{W}  Итог:{RST} " + "  ".join(parts)


_FIELD_COLORS = {
    "email": Y, "phone": G, "phone_number": G, "mobile": G,
    "balance": M, "credit": M, "robux": M,
    "verified": G, "verified_email": G, "email_verified": G,
    "phone_verified": G, "mfa": Y, "nitro": M, "premium": M,
    "country": C, "language": C, "locale": C, "region": C,
    "followers": C, "following": C, "friends": C,
    "karma_total": C, "guilds": C, "posts": C,
    "profile_url": C, "avatar_url": C, "avatar": C,
}


def _render_result(raw, info, service_key):
    masked = mask_cookie(raw)
    svc_name = (SERVICES.get(service_key, {}).get("name", "Unknown")
                if service_key else "Unknown")
    lines = []

    if info is None:
        lines.append(f"{R}  ✗ {RST}{W}{masked}{RST}  {DIM}→{RST}  "
                     f"{R}Empty cookie{RST}")
        return "invalid", lines

    if not info.get("valid"):
        err = info.get("error", "Invalid")
        code = info.get("code", "")
        tag = f" {DIM}[{code}]{RST}" if code else ""
        lines.append(f"{R}  ✗ {RST}{W}{masked}{RST}  {DIM}→{RST}  "
                     f"{R}{err}{RST}{tag}")
        return "invalid", lines

    emoji = "✨"
    cat_name = "Other"
    if service_key:
        cat_key, cat = _categorize(service_key)
        emoji = cat.get("emoji", "✨")
        cat_name = cat.get("name", "Other")

    lines.append(f"{G}  ✓ {RST}{W}{masked}{RST}  {DIM}→{RST}  "
                 f"{G}{B}VALID{RST}  "
                 f"{C}│{RST} {emoji} {B}{svc_name}{RST} "
                 f"{DIM}· {cat_name}{RST}")

    for k, v in info.items():
        if k in ("valid", "service"):
            continue
        key = k.replace("_", " ").title()
        val = fmt_value(v)
        up = str(v).upper()
        if up in ("YES", "TRUE"):
            color = G
        elif up in ("NO", "FALSE", "—"):
            color = DIM + Y
        else:
            color = _FIELD_COLORS.get(k, W)
        lines.append(f"      {DIM}│{RST} {C}{key:<16}{RST}"
                     f"{DIM}:{RST} {color}{val}{RST}")

    lines.append("")
    return "valid", lines


def _emit(lines):
    with _print_lock:
        _clear_progress()
        for ln in lines:
            print(ln)
        with _progress_lock:
            _draw_progress(_last_progress[0], _last_progress[1])


# ─────────────────────────────────────────────────────────────
# ОБРАБОТКА
# ─────────────────────────────────────────────────────────────

def process_one(raw, save=True, dedup=True):
    raw_key = (raw or "").strip()

    if dedup and raw_key:
        h = hashlib.sha1(raw_key.encode("utf-8", "ignore")).hexdigest()
        with _seen_lock:
            if h in _seen_hashes:
                stats.add("dup")
                return "dup", [
                    f"{DIM}  ~ {mask_cookie(raw)}  →  "
                    f"duplicate (skip){RST}"
                ]
            _seen_hashes.add(h)

    jar = parse_cookies(raw)

    if not jar:
        kind, lines = _render_result(raw, None, None)
        stats.add(kind)
        return kind, lines

    svc = detect_service(jar)
    if not svc:
        names = ", ".join(list(jar.keys())[:6])
        masked = mask_cookie(raw)
        lines = [f"{Y}  ? {RST}{W}{masked}{RST}  {DIM}→{RST}  "
                 f"{Y}Unknown service{RST} {DIM}[{names}]{RST}"]
        stats.add("unknown")
        log.debug(f"unknown service: {sanitize_for_log(names)}")
        return "unknown", lines

    # Определяем категорию для статистики
    cat_key, _ = _categorize(svc)

    info = run_check_logged(svc, jar, raw)
    kind, lines = _render_result(raw, info, svc)
    stats.add(kind, service=svc, category=cat_key)

    if (info and not info.get("valid")
            and info.get("code") == "network"
            and CFG.get("retry_network", True)):
        with _retry_lock:
            _retry_items.append(raw)

    if info and info.get("valid"):
        entry = {"service": svc, "category": cat_key,
                 "cookie": raw, "info": info}
        with _collected_lock:
            _collected.append(entry)
        if save:
            save_result(entry)

    return kind, lines


def run_batch(items, _is_retry=False):
    global _use_live_progress
    n = len(items)
    workers = max(1, min(int(CFG.get("workers", 1)), n))
    save = not CFG.get("no_save")
    dedup = bool(CFG.get("deduplicate", True)) and not _is_retry

    _use_live_progress = (workers > 1) and sys.stdout.isatty()

    if not _is_retry:
        print(f"\n{C}▶{RST} Проверяю {B}{n}{RST} строк  "
              f"{DIM}(потоков: {workers}){RST}")
        log.info(f"batch start: {n} items, workers={workers}")
    else:
        print(f"\n{Y}↻{RST} Повторная проверка {B}{n}{RST} строк "
              f"{DIM}(после network-ошибок){RST}")
        log.info(f"retry batch: {n} items")

    with _progress_lock:
        _last_progress[0] = 0
        _last_progress[1] = n
    _draw_progress(0, n, force=True)
    if _use_live_progress:
        print()

    try:
        if workers == 1:
            for i, raw in enumerate(items, 1):
                with _progress_lock:
                    _last_progress[0] = i
                _, lines = process_one(raw, save=save, dedup=dedup)
                _emit(lines)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(process_one, raw, save, dedup)
                           for raw in items]
                done = 0
                for fut in as_completed(futures):
                    done += 1
                    with _progress_lock:
                        _last_progress[0] = done
                    try:
                        _, lines = fut.result()
                    except Exception as e:
                        lines = [f"{R}  ✗ worker error: "
                                 f"{sanitize_for_log(str(e))}{RST}"]
                        log.error(f"worker fail: "
                                  f"{sanitize_for_log(str(e))}")
                    _emit(lines)
    except KeyboardInterrupt:
        _clear_progress()
        print(f"\n{Y}  Прервано пользователем.{RST}")
        log.warning("batch interrupted by user")
    finally:
        _clear_progress()

    s = stats.snapshot()
    log.info(f"batch done: valid={s['valid']} invalid={s['invalid']} "
             f"unknown={s['unknown']} dup={s['duplicate']}")
    print(_stats_report(), "\n")

    # Разбивка по категориям (если что-то найдено)
    if s.get("per_category"):
        cat_line = "  " + f"{DIM}По категориям:{RST} "
        chunks = []
        for cat_key, cnt in sorted(s["per_category"].items(),
                                   key=lambda x: -x[1]):
            meta = CATEGORY_META.get(cat_key, CATEGORY_META["unknown"])
            chunks.append(f"{meta['emoji']} {meta['name']} {B}{cnt}{RST}")
        print(cat_line + "  ".join(chunks), "\n")

    if not _is_retry and CFG.get("retry_network", True):
        with _retry_lock:
            retry_list = list(dict.fromkeys(_retry_items))
            _retry_items.clear()
        if retry_list:
            print(f"{Y}  ↻ Повторная проверка {len(retry_list)} cookies "
                  f"(сетевые ошибки)…{RST}")
            run_batch(retry_list, _is_retry=True)


def finalize_export():
    with _collected_lock:
        entries = list(_collected)
    if not entries:
        return

    output = CFG.get("output_file", "valid_cookies.txt")
    fmt = CFG.get("output_format", "jsonl")

    if fmt == "jsonl" and output == "valid_cookies.txt":
        return

    only_valid = bool(CFG.get("only_valid"))
    if export_results(entries, output, fmt, append=False,
                      only_valid=only_valid):
        print(f"{G}  ✓ Экспортировано {len(entries)} записей → "
              f"{W}{output}{RST} {DIM}[{fmt}]{RST}\n")
        log.info(f"export ok: {output} ({fmt}), {len(entries)} entries")
    else:
        print(f"{R}  ✗ Не удалось записать {output}{RST}\n")
        log.error(f"export fail: {output}")


# ─────────────────────────────────────────────────────────────
# ВЕБХУКИ
# ─────────────────────────────────────────────────────────────

def init_webhooks():
    global _webhook_mgr
    if _webhook_mgr is not None:
        return
    if not is_webhook_ready(CFG):
        log.info("webhooks: disabled")
        return
    try:
        mgr = build_webhooks(CFG)
        if mgr.enabled():
            _webhook_mgr = mgr
            set_webhook_manager(mgr)
            names = [getattr(s, "name", type(s).__name__)
                     for s in mgr.senders]
            log.info(f"webhooks: initialized ({', '.join(names)})")
        else:
            log.info("webhooks: no senders configured")
    except Exception as e:
        log.warning(f"webhooks init fail: {sanitize_for_log(str(e))}")


def shutdown_webhooks():
    global _webhook_mgr
    if _webhook_mgr is None:
        return
    try:
        _webhook_mgr.stop(drain=True, timeout=8.0)
        s = _webhook_mgr.stats()
        log.info(f"webhooks stop: {s}")
    except Exception as e:
        log.warning(f"webhook stop fail: {sanitize_for_log(str(e))}")
    finally:
        _webhook_mgr = None


def test_webhooks():
    if _webhook_mgr is None or not _webhook_mgr.enabled():
        print(f"{Y}  Вебхуки не настроены или отключены.{RST}\n")
        return
    print(f"{C}  Отправляю тестовое сообщение…{RST}\n")
    for name, ok, msg in _webhook_mgr.test_all():
        tag = f"{G}✓ OK{RST}" if ok else f"{R}✗ FAIL{RST}"
        print(f"  {C}{name:<12}{RST} {tag}  "
              f"{DIM}{sanitize_for_log(msg, 120)}{RST}")
    print()


# ─────────────────────────────────────────────────────────────
# РЕЖИМЫ
# ─────────────────────────────────────────────────────────────

def mode_single():
    raw = input(f"\n{B}{M}  Cookie > {RST}").strip()
    if not raw:
        return

    valid_before = stats.valid
    print()
    _, lines = process_one(raw, save=not CFG.get("no_save"),
                           dedup=bool(CFG.get("deduplicate", True)))
    _emit(lines)

    if stats.valid > valid_before:
        print(f"{G}  ✓ Сохранено в "
              f"{CFG.get('output_file', 'valid_cookies.txt')}{RST}\n")


def mode_file():
    path = (input(f"\n{B}{M}  Файл [cookies.txt] > {RST}").strip()
            or "cookies.txt")
    lines = load_file(path)
    if not lines:
        print(f"{R}  Нет данных в {path}{RST}\n")
        return
    run_batch(lines)


def mode_manual():
    print(f"\n{C}  Вставляй cookies по одному. "
          f"Пустая строка — конец.{RST}\n")
    lines = []
    try:
        while True:
            line = input(f"{B}{M}  Cookie > {RST}").strip()
            if not line:
                break
            lines.append(line)
    except (KeyboardInterrupt, EOFError):
        pass

    if not lines:
        return
    run_batch(lines)


# ─────────────────────────────────────────────────────────────
# МЕНЮ
# ─────────────────────────────────────────────────────────────

def _hr(width=54):
    return f"{DIM}{M}{'─' * width}{RST}"


def menu():
    print(BANNER)
    _print_quick_status()
    print(_hr())
    print(f"{B}{W}  Меню{RST}")
    print(_hr())
    print(f"  {M}[1]{RST}  Проверить одну строку cookies")
    print(f"  {M}[2]{RST}  Проверить список из файла {DIM}(cookies.txt){RST}")
    print(f"  {M}[3]{RST}  Вставить список вручную")
    print(_hr())
    print(f"  {M}[4]{RST}  Сервисы {DIM}(что поддерживается){RST}")
    print(f"  {M}[5]{RST}  Настройки {DIM}(config){RST}")
    print(f"  {M}[6]{RST}  Статус {DIM}(лог, прокси, UA, webhooks){RST}")
    print(f"  {M}[7]{RST}  Тест вебхуков")
    print(_hr())
    print(f"  {M}[0]{RST}  Выход")
    print(_hr())
    return input(f"{B}{M}  ❯ {RST}").strip()


def _print_quick_status():
    ua = f"{G}rot{RST}" if CFG.get("rotate_ua") else f"{Y}fix{RST}"
    px_n = len(CFG.get("proxies") or [])
    if CFG.get("rotate_proxy") and px_n:
        px = f"{G}rot({px_n}){RST}"
    else:
        px = f"{DIM}off{RST}"
    lg = CFG.get("log_file") or f"{DIM}—{RST}"
    wh_ok = is_webhook_ready(CFG)
    wh = f"{G}on{RST}" if wh_ok else f"{DIM}off{RST}"
    dd = f"{G}on{RST}" if CFG.get("deduplicate") else f"{DIM}off{RST}"
    w = CFG.get("workers")

    print(f"{DIM}  workers={RST}{W}{w}{RST}  "
          f"{DIM}UA={RST}{ua}  "
          f"{DIM}proxy={RST}{px}  "
          f"{DIM}dedup={RST}{dd}  "
          f"{DIM}webhooks={RST}{wh}")
    print(f"{DIM}  log={RST}{lg}")
    print()


def show_services():
    print(f"\n{B}{W}  Поддерживаемые сервисы:{RST}\n")

    by_cat = {}
    for key, info in SERVICES.items():
        cat_key, _ = _categorize(key)
        by_cat.setdefault(cat_key, []).append((key, info))

    order = ["finance", "social", "email", "gaming", "streaming",
             "marketplace", "productivity", "cloud", "network",
             "database", "unknown"]

    total = 0
    for cat_key in order:
        if cat_key not in by_cat:
            continue
        cat = CATEGORY_META.get(cat_key, CATEGORY_META["unknown"])
        items = by_cat[cat_key]
        total += len(items)
        print(f"  {B}{cat['emoji']}  {cat['name']}{RST}  "
              f"{DIM}({len(items)}){RST}")
        for key, info in items:
            reqs = ", ".join(info.get("required") or
                             info.get("required_any") or
                             info.get("strong") or []) or "—"
            print(f"     {C}{info['name']:<22}{RST} "
                  f"{DIM}required:{RST} {Y}{reqs}{RST}")
        print()

    print(f"{DIM}  Всего: {total} сервисов{RST}\n")


def show_config():
    print(f"\n{B}{W}  Текущие настройки:{RST}\n")
    for k, v in CFG.items():
        if k == "user_agents" and isinstance(v, list):
            v = f"<{len(v)} UA>"
        if k == "proxies" and isinstance(v, list):
            v = f"<{len(v)} proxy>"
        if k == "rate_limit" and isinstance(v, dict):
            v = f"<{len(v)} hosts>"
        if k == "webhooks" and isinstance(v, dict):
            senders = []
            if (v.get("discord") or {}).get("url"):
                senders.append("discord")
            if (v.get("telegram") or {}).get("token"):
                senders.append("telegram")
            if (v.get("slack") or {}).get("url"):
                senders.append("slack")
            if (v.get("generic") or {}).get("url"):
                senders.append("generic")
            v = (f"enabled={v.get('enabled')}, "
                 f"senders=[{', '.join(senders) or '—'}], "
                 f"level={v.get('min_level')}")
        print(f"  {C}{k:<20}{RST} {W}{v!r}{RST}")
    print()


def show_status():
    print(f"\n{B}{W}  Статус:{RST}\n")
    print(f"  {C}{'Лог-файл':<18}{RST} "
          f"{W}{CFG.get('log_file') or '—'}{RST}")
    print(f"  {C}{'Уровень лога':<18}{RST} {W}{CFG.get('log_level')}{RST}")
    print(f"  {C}{'Ротация лога':<18}{RST} "
          f"{W}{CFG.get('log_max_bytes') or 'off'}{RST}")
    print(f"  {C}{'Ротация UA':<18}{RST} {W}{CFG.get('rotate_ua')}{RST}")
    print(f"  {C}{'Пул UA':<18}{RST} "
          f"{W}{len(CFG.get('user_agents') or [])}{RST}")
    print(f"  {C}{'Ротация прокси':<18}{RST} "
          f"{W}{CFG.get('rotate_proxy')}{RST}")
    print(f"  {C}{'Список прокси':<18}{RST} "
          f"{W}{len(CFG.get('proxies') or [])}{RST}")
    print(f"  {C}{'Прокси-чек':<18}{RST} "
          f"{W}{CFG.get('proxy_check_on_start')} "
          f"(workers={CFG.get('proxy_check_workers')}){RST}")
    rl = CFG.get("rate_limit") or {}
    print(f"  {C}{'Rate limit':<18}{RST} "
          f"{W}default={rl.get('default')}, hosts={max(0, len(rl) - 1)}{RST}")
    print(f"  {C}{'Дедупликация':<18}{RST} "
          f"{W}{CFG.get('deduplicate')}{RST}")
    print(f"  {C}{'Retry network':<18}{RST} "
          f"{W}{CFG.get('retry_network')}{RST}")

    wh = CFG.get("webhooks") or {}
    senders = []
    if (wh.get("discord") or {}).get("url"):
        senders.append("discord")
    if (wh.get("telegram") or {}).get("token") and \
       (wh.get("telegram") or {}).get("chat_id"):
        senders.append("telegram")
    if (wh.get("slack") or {}).get("url"):
        senders.append("slack")
    if (wh.get("generic") or {}).get("url"):
        senders.append("generic")

    print(f"  {C}{'Webhooks':<18}{RST} "
          f"{W}{bool(wh.get('enabled'))} "
          f"({', '.join(senders) or '—'}){RST}")
    print(f"  {C}{'  min_level':<18}{RST} "
          f"{W}{wh.get('min_level', 'all')}{RST}")
    print(f"  {C}{'  dedup':<18}{RST} {W}{wh.get('dedup', True)}{RST}")
    if wh.get("only_services"):
        print(f"  {C}{'  only_services':<18}{RST} "
              f"{W}{wh.get('only_services')}{RST}")
    if wh.get("only_categories"):
        print(f"  {C}{'  only_categories':<18}{RST} "
              f"{W}{wh.get('only_categories')}{RST}")
    print()


def interactive_loop():
    while True:
        try:
            choice = menu()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{M}  Выход.{RST}")
            break

        if choice == "0":
            print(f"\n{M}  До встречи!{RST}\n")
            break
        elif choice == "1":
            mode_single()
        elif choice == "2":
            mode_file()
        elif choice == "3":
            mode_manual()
        elif choice == "4":
            show_services()
        elif choice == "5":
            show_config()
        elif choice == "6":
            show_status()
        elif choice == "7":
            test_webhooks()
        else:
            print(f"{R}  Неверный выбор.{RST}\n")

        try:
            input(f"{C}  Enter — назад в меню…{RST}")
        except (KeyboardInterrupt, EOFError):
            break
        clear()


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        prog="checker",
        description="Universal Cookie Checker — by Qwixx",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python main.py\n"
            "  python main.py -f cookies.txt -w 8\n"
            "  python main.py -c 'p20t=xyz'\n"
            "  python main.py -f list.txt -o out.csv --format csv --only-valid\n"
            "  python main.py -f list.txt --log-file checker.log --log-level DEBUG\n"
            "  python main.py --test-webhooks\n"
            "  python main.py --save-config\n"
            "  python main.py --list-services\n"
        ),
    )
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {VERSION}")
    p.add_argument("-f", "--file", help="Файл со списком cookies")
    p.add_argument("-c", "--cookie", help="Одна строка cookies")
    p.add_argument("-w", "--workers", type=int, help="Число потоков")
    p.add_argument("-o", "--output", help="Путь для экспорта результатов")
    p.add_argument("--format", choices=["jsonl", "json", "csv", "txt"],
                   help="Формат экспорта результатов")
    p.add_argument("--only-valid", action="store_true",
                   help="Экспортировать только валидные")
    p.add_argument("--no-save", action="store_true",
                   help="Не сохранять валидные в valid_cookies.txt")
    p.add_argument("--no-dedup", action="store_true",
                   help="Отключить дедупликацию cookies")
    p.add_argument("--no-webhooks", action="store_true",
                   help="Отключить вебхуки на этот запуск")
    p.add_argument("--no-live-progress", action="store_true",
                   help="Отключить живой прогресс-бар")
    p.add_argument("--test-webhooks", action="store_true",
                   help="Отправить тестовое сообщение и выйти")
    p.add_argument("--log-file", help="Путь к лог-файлу")
    p.add_argument("--log-level",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                   help="Уровень логирования")
    p.add_argument("--list-services", action="store_true",
                   help="Показать список поддерживаемых сервисов и выйти")
    p.add_argument("--config", help="Путь к config.json")
    p.add_argument("--save-config", action="store_true",
                   help="Сохранить текущие настройки в config.json")
    return p.parse_args()


def main():
    global CFG, _use_live_progress

    args = parse_args()
    CFG = load_config(args.config)

    if args.workers is not None:
        CFG["workers"] = args.workers
    if args.only_valid:
        CFG["only_valid"] = True
    if args.output:
        CFG["output_file"] = args.output
    if args.format:
        CFG["output_format"] = args.format
    if args.no_save:
        CFG["no_save"] = True
    if args.no_dedup:
        CFG["deduplicate"] = False
    if args.no_webhooks:
        wh = dict(CFG.get("webhooks") or {})
        wh["enabled"] = False
        CFG["webhooks"] = wh
    if args.log_file:
        CFG["log_file"] = args.log_file
    if args.log_level:
        CFG["log_level"] = args.log_level
    if args.no_live_progress:
        _use_live_progress = False

    setup_logger(
        CFG.get("log_file") or "",
        CFG.get("log_level") or "INFO",
        max_bytes=int(CFG.get("log_max_bytes") or 0),
        backup_count=int(CFG.get("log_backup_count") or 3),
    )
    log.info(f"checker start; workers={CFG.get('workers')}")

    if args.save_config:
        path = args.config or "config.json"
        if save_config(CFG, args.config):
            print(f"{G}  ✓ Config saved → {path}{RST}")
            log.info(f"config saved: {path}")
        else:
            print(f"{R}  ✗ Не удалось сохранить config{RST}")
        return

    if args.list_services:
        print(BANNER)
        show_services()
        return

    init_webhooks()

    if args.test_webhooks:
        print(BANNER)
        test_webhooks()
        shutdown_webhooks()
        return

    configure_checkers(CFG)
    log.info(f"checkers configured: rotate_ua={CFG.get('rotate_ua')}, "
             f"rotate_proxy={CFG.get('rotate_proxy')}, "
             f"proxies={len(CFG.get('proxies') or [])}")

    try:
        if args.cookie:
            print(BANNER)
            _, lines = process_one(args.cookie,
                                   save=not CFG.get("no_save"),
                                   dedup=bool(CFG.get("deduplicate", True)))
            _emit(lines)
            print(_stats_report(), "\n")
            finalize_export()
            return

        if args.file:
            print(BANNER)
            items = load_file(args.file)
            if not items:
                print(f"{R}  Нет данных в {args.file}{RST}\n")
                return
            run_batch(items)
            finalize_export()
            return

        interactive_loop()
    finally:
        shutdown_webhooks()
        finalize_export()
        log.info("checker stop")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{M}  Прервано.{RST}")
        sys.exit(0)