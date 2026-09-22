<div align="center">
<img src="https://capsule-render.vercel.app/api?type=waving&height=180&color=gradient&text=Universal%20Cookie%20Checker&fontSize=44&fontColor=ffffff&desc=Auto-detect%20%26%20validate%20cookies&descSize=16&descAlignY=68" width="100%"/>
</div>

<p align="center">
<img src="https://img.shields.io/badge/Python-3.10%2B-5865F2?style=for-the-badge&logo=python&logoColor=white"/>
<img src="https://img.shields.io/badge/Version-1.0-5865F2?style=for-the-badge"/>
<img src="https://img.shields.io/badge/License-MIT-5865F2?style=for-the-badge"/>
</p>

---

## ✨ Что делает

- 🔍 **Автоматически определяет сервис** по названиям cookies — ничего настраивать не нужно
- ✅ Проверяет валидность cookies
- 📋 Выводит полную информацию об аккаунте
- 📦 Три режима: одна строка, список из файла, вставить вручную
- 💾 Сохраняет валидные cookies в `valid_cookies.txt` (JSON-Lines)
- 📊 Показывает статистику сессии (valid / invalid / unknown)
- 🎨 Красивый цветной вывод
- ⚡ Паузы между запросами + автоматические ретраи (сетевые сбои, 429, 5xx)
- 🛡 Детект Cloudflare-челленджей и rate-limit
- 🔌 Поддержка прокси (`PROXY` в `checkers.py`)

---

## 🎯 Поддерживаемые сервисы

| Сервис | Что выводит |
|---|---|
| **Steam** | steamID, персона, реалнейм, локация, аватар, VAC-бан, trade-бан, лимит-аккаунт, кол-во предметов, валидность сессии |
| **Roblox** | ID, username, display name, дата создания, Robux, Premium, email, phone, followers/following/friends, verified, banned |
| **Netflix** | email, план, страна, дата регистрации, количество профилей |
| **Spotify** | username, email, display name, страна, продукт, birthdate, gender |
| **Twitch** | ID, login, email, email_verified, тип, broadcaster_type, дата создания, followers |
| **VK** | user_id, имя, ссылка на профиль |

---

## 🚀 Установка

**1. Клонировать**

`git clone https://github.com/QwixxTwix/cookie-checker.git`

`cd cookie-checker`

**2. Установить зависимости**

`pip install -r requirements.txt`

**3. Запуск**

- **Windows:** двойной клик по `run.bat`
- **Linux / macOS:** `bash run.sh`

---

## 🎯 Использование

При запуске откроется меню:

- **[1]** Проверить одну строку cookies
- **[2]** Проверить список из файла (`cookies.txt`)
- **[3]** Вставить список вручную
- **[4]** Показать поддерживаемые сервисы
- **[0]** Выход

**Форматы cookies, которые принимаются:**
- Строка: `name=value; name2=value2`
- JSON-массив (Cookie-Editor / EditThisCookie)
- JSON-объект `{name: value, ...}`
- Netscape `cookies.txt`

---

## 📁 Куда сохраняются валидные cookies

Все рабочие cookies автоматически пишутся в `valid_cookies.txt` в формате JSON-Lines. Каждая запись содержит `service`, `cookie`, `info` и `checked_at`.

---

## ⚙️ Технические детали

- **Timeout:** 15 сек
- **Retry:** до 2 повторных попыток (сетевые сбои, 429 с Retry-After, 5xx)
- **User-Agent:** Chrome 120 (спуфинг)
- **Rate-limit:** пауза 0.7с между запросами
- **Формат сохранения:** JSON Lines
- **Авто-определение сервиса** по названиям cookies
- **Детект ошибок:** invalid / network / cf / rate_limit / parse / unknown / session

---

## 🔌 Прокси

В `checkers.py` найди строку:

```python

PROXY = None
и замени на:

python
PROXY = {"http": "http://user:pass@ip:port", "https": "http://user:pass@ip:port"}
⚠️ Дисклеймер
Инструмент создан исключительно в образовательных целях.
Проверяй только свои cookies.
Использование чужих cookies — нарушение ToS сервисов и может преследоваться по закону.
Автор не несёт ответственности за любое использование.
```

<div align="center">
by <a href="https://github.com/QwixxTwix">QwixxTwix</a>

⭐ Если помогло — поставь звезду

</div>
