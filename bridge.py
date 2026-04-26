"""
Discord -> Telegram signal bridge.

Listens to one or more Discord channels via the gateway (user token)
and forwards every new message to Telegram via a bot.

ToS note: this uses a user token (self-bot), which violates Discord ToS.
Jitter + rate limiting reduce detection risk but do not eliminate it.
Use a secondary Discord account if you can.
"""
import asyncio
import logging
import os
import random
import sys

import discord  # discord.py-self, NOT discord.py
import requests

# ---------- Config (via env vars on Railway) ----------
DISCORD_USER_TOKEN = os.environ["DISCORD_USER_TOKEN"]
CHANNEL_IDS = {int(x.strip()) for x in os.environ["CHANNEL_IDS"].split(",") if x.strip()}
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
PREFIX_CHANNEL_NAME = os.environ.get("PREFIX_CHANNEL_NAME", "true").lower() == "true"
MAX_MSG_LEN = 4000  # Telegram limit is 4096

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bridge")

# ---------- Telegram ----------
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

def send_telegram(body: str) -> None:
    if not body.strip():
        return
    if len(body) > MAX_MSG_LEN:
        body = body[: MAX_MSG_LEN - 3] + "..."
    try:
        r = requests.post(
            TELEGRAM_URL,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": body,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if r.ok:
            log.info(f"Telegram sent: message_id={r.json().get('result', {}).get('message_id')}")
        else:
            log.error(f"Telegram send failed: {r.status_code} {r.text}")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")

# ---------- Discord ----------
class Bridge(discord.Client):
    async def on_ready(self):
        log.info(f"Connected as {self.user} (id={self.user.id})")
        log.info(f"Watching channels: {sorted(CHANNEL_IDS)}")

    async def on_message(self, message: discord.Message):
        if message.channel.id not in CHANNEL_IDS:
            return
        if message.author.id == self.user.id:
            return

        author = message.author.display_name or str(message.author)
        channel_name = getattr(message.channel, "name", "dm")

        parts = []
        if PREFIX_CHANNEL_NAME:
            parts.append(f"[#{channel_name}] {author}:")
        else:
            parts.append(f"{author}:")

        if message.content:
            parts.append(message.content)

        for att in message.attachments:
            parts.append(att.url)

        for emb in message.embeds:
            if emb.title:
                parts.append(f"[{emb.title}]")
            if emb.description:
                parts.append(emb.description)

        body = "\n".join(parts).strip()
        if not body:
            return

        log.info(f"Forwarding message from #{channel_name} ({len(body)} chars)")
        await asyncio.sleep(random.uniform(0.3, 1.2))
        await asyncio.to_thread(send_telegram, body)

def main():
    client = Bridge()
    while True:
        try:
            client.run(DISCORD_USER_TOKEN, log_handler=None)
        except KeyboardInterrupt:
            log.info("Shutdown requested.")
            sys.exit(0)
        except Exception as e:
            wait = random.uniform(30, 90)
            log.error(f"Client crashed: {e!r}. Reconnecting in {wait:.0f}s")
            import time
            time.sleep(wait)

if __name__ == "__main__":
    main()
