"""
Discord -> WhatsApp signal bridge.

Listens to one or more Discord channels via the gateway (user token)
and forwards every new message to WhatsApp via Twilio.

ToS note: this uses a user token (self-bot), which violates Discord ToS.
Jitter + rate limiting reduce detection risk but do not eliminate it.
Use a secondary Discord account if you can.
"""

import asyncio
import logging
import os
import random
import sys
from datetime import datetime

import discord  # discord.py-self, NOT discord.py
from twilio.rest import Client as TwilioClient

# ---------- Config (via env vars on Railway) ----------
DISCORD_USER_TOKEN = os.environ["DISCORD_USER_TOKEN"]
CHANNEL_IDS = {int(x.strip()) for x in os.environ["CHANNEL_IDS"].split(",") if x.strip()}

TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_FROM = os.environ["TWILIO_WHATSAPP_FROM"]  # e.g. whatsapp:+14155238886
WHATSAPP_TO = os.environ["WHATSAPP_TO"]                    # e.g. whatsapp:+34...

# Optional: prefix every WhatsApp message with channel name for clarity
PREFIX_CHANNEL_NAME = os.environ.get("PREFIX_CHANNEL_NAME", "true").lower() == "true"

# WhatsApp message hard limit is 1600 chars; keep buffer
MAX_MSG_LEN = 1500

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bridge")

# ---------- Twilio ----------
twilio = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def send_whatsapp(body: str) -> None:
    """Send a WhatsApp message. Swallows exceptions so a Twilio blip
    never crashes the Discord listener."""
    if not body.strip():
        return
    if len(body) > MAX_MSG_LEN:
        body = body[: MAX_MSG_LEN - 3] + "..."
    try:
        msg = twilio.messages.create(
            body=body,
            from_=TWILIO_WHATSAPP_FROM,
            to=WHATSAPP_TO,
        )
        log.info(f"Twilio sent: sid={msg.sid}")
    except Exception as e:
        log.error(f"Twilio send failed: {e}")


# ---------- Discord ----------
class Bridge(discord.Client):
    async def on_ready(self):
        log.info(f"Connected as {self.user} (id={self.user.id})")
        log.info(f"Watching channels: {sorted(CHANNEL_IDS)}")

    async def on_message(self, message: discord.Message):
        # Only forward messages from target channels.
        if message.channel.id not in CHANNEL_IDS:
            return
        # Don't forward our own messages (prevents any accidental loop).
        if message.author.id == self.user.id:
            return

        # Build the message body. Include author + content + attachment URLs.
        author = message.author.display_name or str(message.author)
        channel_name = getattr(message.channel, "name", "dm")

        parts = []
        if PREFIX_CHANNEL_NAME:
            parts.append(f"[#{channel_name}] {author}:")
        else:
            parts.append(f"{author}:")

        if message.content:
            parts.append(message.content)

        # Attachments — include URLs so screenshots/charts still reach you.
        for att in message.attachments:
            parts.append(att.url)

        # Embeds often contain the actual signal text when bots post.
        for emb in message.embeds:
            if emb.title:
                parts.append(f"[{emb.title}]")
            if emb.description:
                parts.append(emb.description)

        body = "\n".join(parts).strip()
        if not body:
            return

        log.info(f"Forwarding message from #{channel_name} ({len(body)} chars)")

        # Small jitter so we're not firing the API at a perfectly deterministic
        # millisecond after every message — reduces pattern-matching flags.
        await asyncio.sleep(random.uniform(0.3, 1.2))

        # Run Twilio call in a thread so the gateway heartbeat isn't blocked.
        await asyncio.to_thread(send_whatsapp, body)


def main():
    intents = discord.Intents.default()
    intents.message_content = True  # ignored by self-bot but harmless

    client = Bridge()

    while True:
        try:
            # chunk_guilds_at_startup=False reduces fingerprint (smaller handshake).
            client.run(DISCORD_USER_TOKEN, log_handler=None)
        except KeyboardInterrupt:
            log.info("Shutdown requested.")
            sys.exit(0)
        except Exception as e:
            # Discord gateway disconnects happen; exponential-ish backoff.
            wait = random.uniform(30, 90)
            log.error(f"Client crashed: {e!r}. Reconnecting in {wait:.0f}s")
            # Small sleep via blocking call because event loop is dead here.
            import time

            time.sleep(wait)


if __name__ == "__main__":
    main()
