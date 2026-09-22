<div align="center">

# 🍪 Universal Cookie Checker

<img width="560" alt="Universal Cookie Checker" src="https://github.com/user-attachments/assets/6a8f970e-d352-4c2d-8a3d-23c7054be23d" />

**Auto-detect & validate cookies — 51 сервис, вебхуки, категории, прокси**

![Python](https://img.shields.io/badge/Python-3.10%2B-5865F2?style=for-the-badge&logo=python&logoColor=white)
![Version](https://img.shields.io/badge/Version-1.0-5865F2?style=for-the-badge)
![Services](https://img.shields.io/badge/Services-51-5865F2?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-5865F2?style=for-the-badge)

</div>

---

## ✨ Что делает

- 🔍 **Автоматически определяет сервис** по названиям cookies — ничего настраивать не нужно
- ✅ Проверяет валидность cookies и выводит полную инфу об аккаунте
- 📦 Три режима: одна строка, список из файла, вставить вручную
- 🗂 **Категории сервисов** — finance, social, email, gaming, streaming, marketplace, productivity, cloud, network, database
- 💾 Сохраняет валидные cookies в `valid_cookies.txt` (JSON-Lines)
- 📊 Живой прогресс-бар + статистика по сервисам и категориям
- 🎨 Красивый цветной вывод: эмодзи категорий, цветные поля, компактное меню
- 🔔 **Вебхуки**: Discord, Telegram, Slack, Generic — с эмодзи, цветами, кнопками «Профиль», фильтрами по категориям
- ⚡ Rate-limit на хост + автоматические ретраи (сетевые сбои, 429 с `Retry-After`, 5xx)
- 🔄 Ротация User-Agent + ротация прокси с проверкой живости
- 🛡 Детект Cloudflare-челленджей и rate-limit
- ⚙️ Полная конфигурация через `config.json`

---

## 🎯 Поддерживаемые сервисы (51)

### 💰 Finance
`Binance` · `Coinbase` · `PayPal` · `Stripe` · `Kraken` · `MetaMask` · `Trust Wallet` · `OpenSea`

### 💬 Social
`Telegram (Web)` · `Instagram` · `Facebook` · `VK` · `WhatsApp (Web)` · `Discord` · `Twitter/X` · `Reddit` · `LinkedIn` · `TikTok` · `Twitch`

### 📧 Email
`Proton Mail` · `Yahoo Mail` · `Mail.ru` · `Google Workspace` · `Microsoft 365`

### 🎮 Gaming
`Steam` · `Epic Games` · `Riot Games` · `Battle.net` · `Xbox` · `Roblox`

### 📺 Streaming
`Netflix` · `Spotify`

### 🛒 Marketplace
`Amazon` · `eBay` · `Airbnb`

### 📊 Productivity
`Slack` · `Jira` · `Notion` · `Trello` · `Dropbox` · `GitHub` · `GitLab` · `Bitbucket`

### ☁️ Cloud
`AWS` · `Azure` · `DigitalOcean` · `Cloudflare Dashboard`

### 🔒 Network
`OpenVPN` · `WireGuard`

### 🗄️ Database
`Adminer` · `phpMyAdmin`

**Что выводится (примеры):**

| Сервис | Информация |
|---|---|
| **Steam** | steamID, персона, аватар, VAC/trade-бан, лимит-аккаунт, кол-во предметов, валидность сессии |
| **Roblox** | ID, username, display name, Robux, email, профиль |
| **Discord** | ID, tag, email, phone, MFA, Nitro, кол-во гильдий, аватар |
| **Instagram** | username, full name, followers/following/posts, verified, business |
| **Binance** | userId, email, phone, KYC, VIP-level, country |
| **Netflix** | email, план, страна |
| **Spotify** | username, email, страна, план (product) |
| **Twitch** | ID, login, email, created_at |
| **Twitter/X** | username, display name, email, phone, verified, protected |
| **Reddit** | username, karma (link+comment), gold, mod |
| **GitHub** | username, name, user_id, avatar |
| **Epic Games** | ID, displayName, email, country |
| **Battle.net** | battletag |
| **Xbox** | xuid, gamertag |
| **Proton Mail** | ID, email, display name, credit, subscribed |

---

## 🚀 Установка

**1. Клонировать репозиторий**

```
git clone https://github.com/QwixxTwix/cookie-checker.git
cd cookie-checker
```

**2. Установить зависимости**

```
pip install -r requirements.txt
```

**3. Запуск**

- **Windows:** двойной клик по `run.bat`
- **Linux / macOS:** `bash run.sh`

---

## 🎯 Использование

### Интерактивное меню

```
  workers=4  UA=rot  proxy=off  dedup=on  webhooks=on
  log=—

──────────────────────────────────────────────────────
  Меню
──────────────────────────────────────────────────────
  [1]  Проверить одну строку cookies
  [2]  Проверить список из файла (cookies.txt)
  [3]  Вставить список вручную
──────────────────────────────────────────────────────
  [4]  Сервисы (что поддерживается)
  [5]  Настройки (config)
  [6]  Статус (лог, прокси, UA, webhooks)
  [7]  Тест вебхуков
──────────────────────────────────────────────────────
  [0]  Выход
──────────────────────────────────────────────────────
```

### CLI

```
python main.py                                  # интерактивное меню
python main.py -f cookies.txt -w 8              # из файла, 8 потоков
python main.py -c "p20t=..."                    # одна строка
python main.py -f list.txt -o out.csv --format csv --only-valid
python main.py -f list.txt --log-file run.log --log-level DEBUG
python main.py --test-webhooks                  # тест вебхуков
python main.py --list-services                  # список сервисов
python main.py --save-config                    # сохранить config.json
```

**Форматы cookies, которые принимаются:**

- Строка: `name=value; name2=value2`
- JSON-массив (Cookie-Editor / EditThisCookie)
- JSON-объект `{name: value, ...}`
- Netscape `cookies.txt`

---

## 📁 Куда сохраняются валидные cookies

Все рабочие cookies автоматически пишутся в `valid_cookies.txt` в формате **JSON-Lines**:

```
{"service": "steam", "category": "gaming", "cookie": "...", "info": {...}, "checked_at": "2026-01-01T00:00:00Z"}
```

Можно экспортировать в **json / csv / txt** через флаг `--format` + `--output`.

---

## ⚙️ Конфигурация (`config.json`)

Создать можно вручную или командой `python main.py --save-config`.

**Основные ключи:**

```
{
  "workers": 4,
  "timeout": 15,
  "max_retries": 2,

  "rotate_ua": true,
  "proxy": null,
  "proxies": [],
  "rotate_proxy": true,
  "proxy_check_on_start": true,

  "rate_limit": {
    "default": 5,
    "steamcommunity.com": 3,
    "www.netflix.com": 2
  },

  "output_file": "valid_cookies.txt",
  "output_format": "jsonl",
  "only_valid": false,
  "deduplicate": true,
  "retry_network": true,

  "log_file": "",
  "log_level": "INFO",

  "webhooks": { "enabled": false }
}
```

Полный список — в `config.py` (константа `DEFAULT_CONFIG`).

---

## 🔔 Вебхуки

Поддерживаются **Discord**, **Telegram**, **Slack** и **Generic** (любой URL). Работают асинхронно, с дедупликацией и rate-limit (3 сообщения/сек).

### Фильтры

- `only_services` — список конкретных сервисов (пусто = все)
- `only_categories` — список категорий: `finance`, `social`, `email`, `gaming`, `streaming`, `marketplace`, `productivity`, `cloud`, `network`, `database`
- `min_level` — `"all"` (все) или `"premium"` (только с email / phone / balance / nitro / robux и т.п.)
- `min_info_fields` — минимум полей в info
- `dedup` — не отправлять один и тот же cookie дважды

### Пример: Discord + только финансы

```
{
  "webhooks": {
    "enabled": true,
    "only_categories": ["finance", "email"],
    "discord": {
      "url": "https://discord.com/api/webhooks/xxx/yyy",
      "username": "Cookie Checker",
      "mention_role_id": "",
      "show_category": true
    }
  }
}
```

### Пример: Telegram с кнопкой «Профиль»

```
{
  "webhooks": {
    "enabled": true,
    "telegram": {
      "token": "123456:ABC...",
      "chat_id": "-1001234567890",
      "silent": false,
      "with_button": true
    }
  }
}
```

### Что в сообщении

- Эмодзи категории (💰 💬 📧 🎮 📺 🛒 📊 ☁️ 🔒 🗄️)
- Цвет эмбеда под сервис (напр. Spotify — зелёный, Netflix — красный, Discord — синий)
- Ссылка на профиль (кнопка в Telegram/Slack, url в Discord)
- Аватарка Discord (если проверяется Discord-токен)
- Все поля info (email, phone, баланс, Robux, Nitro и т.д.)
- Маскированный cookie

Тест: `python main.py --test-webhooks`

---

## 🔌 Прокси

В `config.json` (или через `--save-config`):

```
{
  "rotate_proxy": true,
  "proxy_check_on_start": true,
  "proxy_check_workers": 10,
  "proxies": [
    {"http": "http://user:pass@ip:port", "https": "http://user:pass@ip:port"},
    {"http": "socks5://ip:port", "https": "socks5://ip:port"}
  ]
}
```

При старте мёртвые прокси автоматически отсеиваются (параллельная проверка).

Для SOCKS: `pip install PySocks`.

---

## ⚙️ Технические детали

| Параметр | Значение |
|---|---|
| **Timeout** | 15 сек |
| **Retry** | до 2 повторных (сеть, 429 с `Retry-After`, 5xx) |
| **User-Agent** | пул из 10 реальных UA, ротация |
| **Rate-limit** | per-host, настраивается в `config.json` |
| **Формат сохранения** | JSON Lines (по умолчанию) |
| **Экспорт** | jsonl / json / csv / txt |
| **Авто-определение** | по названиям cookies (`strong`, `strong_prefixes`, `value_patterns`, `required`, `required_any`, `weak`) |
| **Коды ошибок** | `invalid` / `network` / `cf` / `rate_limit` / `parse` / `unsupported` |
| **Вебхуки** | async, dedup, 3 msg/sec, retry с backoff |

---

## 📂 Структура проекта

```
cookie-checker/
├── main.py             # точка входа, UI, меню, CLI
├── checkers.py         # 51 чекер + конфиг сессии
├── services.py         # детект сервиса по cookies
├── config.py           # дефолтный конфиг
├── utils.py            # парсинг, маскирование, экспорт, логгер
├── webhooks.py         # Discord / Telegram / Slack / Generic
├── proxy_checker.py    # проверка живости прокси
├── run.bat / run.sh    # лончеры
├── requirements.txt
├── pyproject.toml
├── config.json         # (создаётся вручную или --save-config)
└── valid_cookies.txt   # (создаётся автоматически)
```

---

## ⚠️ Дисклеймер

> Инструмент создан исключительно в образовательных целях.
> Проверяй **только свои** cookies.
> Использование чужих cookies — нарушение ToS сервисов и может преследоваться по закону.
> Автор не несёт ответственности за любое использование.

---

<div align="center">

**by <a href="https://github.com/QwixxTwix">QwixxTwix</a>**

⭐ Если помогло — поставь звезду

</div>
