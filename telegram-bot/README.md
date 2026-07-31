# Telegram Bot

A Telegram bot built with [aiogram 3.x](https://docs.aiogram.dev/).

## Setup

### 1. Add your Bot Token

Set the `BOT_TOKEN` secret in your Replit project (Secrets tab → `BOT_TOKEN`).
Get a token from [@BotFather](https://t.me/BotFather) on Telegram.

### 2. Add the welcome video

Place your video file at:

```
telegram-bot/welcome.mp4
```

The bot will fall back to sending the text message only if the file is missing.

### 3. Install dependencies

```bash
pip install -r telegram-bot/requirements.txt
```

### 4. Run the bot

```bash
python telegram-bot/bot.py
```

## Behaviour

| Trigger | Response |
|---------|----------|
| `/start` | Sends `welcome.mp4` + welcome text + inline button |
| Button press | Opens `https://www.guardiola66.com/login` |
