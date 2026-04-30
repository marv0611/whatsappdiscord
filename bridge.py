"""
Discord -> Telegram signal bridge.
Listens to one or more Discord channels via the gateway (user token)
and forwards every new message to Telegram via a bot.

Includes message backfill polling and forced periodic reconnects
to mitigate self-bot gateway gap issues.
"""
import asyncio
import logging
import os
import random
import sys
import time

import discord  # discord.py-self
import requests

# ---------- Config (via env vars on Railway) ----------
DISCORD_USER_TOKEN = os.environ["DISCORD_USER_TOKEN"]
CHANNEL_IDS = {int(x.strip()) for x in os.environ["CHANNEL_IDS"].split(",") if x.strip()}
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
PREFIX_CHANNEL_NAME = os.environ.get("PREFIX_CHANNEL_NAME", "true").lower() == "true"

# New: how often to poll each channel for missed messages (seconds)
BACKFILL_INTERVAL = int(os.environ.get("BACKFILL_INTERVAL", "300"))  # 5 min
# New: force a full reconnect every N seconds (0 = disabled)
FORCE_RECONNECT_INTERVAL = int(os.environ.get("FORCE_RECONNECT_INTERVAL", "10800"))  # 3 hr

MAX_MSG_LEN = 4000

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


# ---------- Bridge ----------
class Bridge(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track last-seen message ID per channel, so backfill knows where to resume
        self.last_seen = {cid: None for cid in CHANNEL_IDS}
        self._start_time = time.time()

    async def on_ready(self):
        log.info(f"Connected as {self.user} (id={self.user.id})")
        log.info(f"Watching channels: {sorted(CHANNEL_IDS)}")
        # Initialize last_seen with the most recent message in each channel
        for cid in CHANNEL_IDS:
            try:
                ch = self.get_channel(cid) or await self.fetch_channel(cid)
                async for msg in ch.history(limit=1):
                    self.last_seen[cid] = msg.id
                    log.info(f"Initialized last_seen for #{getattr(ch, 'name', cid)}: {msg.id}")
            except Exception as e:
                log.error(f"Could not init last_seen for {cid}: {e!r}")

        # Start background tasks
        self.loop.create_task(self.backfill_loop())
        if FORCE_RECONNECT_INTERVAL > 0:
            self.loop.create_task(self.reconnect_watchdog())

    async def on_message(self, message: discord.Message):
        if message.channel.id not in CHANNEL_IDS:
            return
        if message.author.id == self.user.id:
            return
        await self._forward(message)
        # Update last_seen
        if (self.last_seen.get(message.channel.id) or 0) < message.id:
            self.last_seen[message.channel.id] = message.id

    async def _forward(self, message: discord.Message):
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
        log.info(f"Forwarding from #{channel_name} (msg_id={message.id}, {len(body)} chars)")
        await asyncio.sleep(random.uniform(0.3, 1.2))
        await asyncio.to_thread(send_telegram, body)

    async def backfill_loop(self):
        """Every BACKFILL_INTERVAL seconds, fetch any messages newer than last_seen."""
        await asyncio.sleep(BACKFILL_INTERVAL)
        while not self.is_closed():
            for cid in CHANNEL_IDS:
                try:
                    ch = self.get_channel(cid) or await self.fetch_channel(cid)
                    after_id = self.last_seen.get(cid)
                    if after_id is None:
                        continue
                    after_obj = discord.Object(id=after_id)
                    missed = []
                    async for msg in ch.history(limit=50, after=after_obj, oldest_first=True):
                        if msg.author.id == self.user.id:
                            continue
                        missed.append(msg)
                    if missed:
                        log.warning(f"Backfill caught {len(missed)} missed messages in #{getattr(ch, 'name', cid)}")
                        for msg in missed:
                            await self._forward(msg)
                            if msg.id > (self.last_seen.get(cid) or 0):
                                self.last_seen[cid] = msg.id
                except Exception as e:
                    log.error(f"Backfill error for {cid}: {e!r}")
            await asyncio.sleep(BACKFILL_INTERVAL)

    async def reconnect_watchdog(self):
        """Force a full reconnect after FORCE_RECONNECT_INTERVAL seconds."""
        await asyncio.sleep(FORCE_RECONNECT_INTERVAL)
        log.warning(f"Forcing reconnect after {FORCE_RECONNECT_INTERVAL}s uptime")
        await self.close()  # outer loop in main() will restart


def main():
    while True:
        client = Bridge()
        try:
            client.run(DISCORD_USER_TOKEN, log_handler=None)
        except KeyboardInterrupt:
            log.info("Shutdown requested.")
            sys.exit(0)
        except Exception as e:
            log.error(f"Client crashed: {e!r}")
        wait = random.uniform(15, 45)
        log.warning(f"Restarting in {wait:.0f}s")
        time.sleep(wait)


if __name__ == "__main__":
    main()
