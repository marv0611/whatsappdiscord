# Discord → WhatsApp Signal Bridge

Forwards every message in a chosen Discord channel to your WhatsApp via Twilio.
Runs 24/7 on Railway for ~free.

**ToS warning:** this uses a Discord user token (self-bot), which violates
Discord's Terms of Service. Ban risk is real but low with the rate-limiting
and jitter built into this code. **Recommended: create a secondary Discord
account, pay for the signals group on *that* account, and run the bridge
from it.** Losing a throwaway account stings less than losing the one you
actually use.

---

## Part 1 — Twilio (5 min)

1. Sign up at **twilio.com** (free trial includes ~$15 credit, more than
   enough to validate).
2. In the console, go to **Messaging → Try it out → Send a WhatsApp message**.
3. You'll see a sandbox number (e.g. `+1 415 523 8886`) and a join code like
   `join silver-hammer`.
4. On your phone, open WhatsApp and send `join silver-hammer` to that number.
   You'll get a confirmation back.
5. In the Twilio console sidebar, grab **Account SID** and **Auth Token**
   from the dashboard. These go in your env vars.

**Cost:** WhatsApp sandbox messages to you are billed at standard Twilio
rates, roughly $0.005 per outbound message. 200 signals/month ≈ $1.

**Sandbox gotcha:** the sandbox session expires 72 hours after the last
inbound message from you. If messages stop arriving, send any text to the
sandbox number and it reactivates. For a permanent solution, register your
own WhatsApp sender (requires Meta Business approval — not worth it for
personal use).

---

## Part 2 — Get your Discord user token (2 min)

**Do this in a private browser window so you don't accidentally screenshot
it later.**

1. Open **discord.com/app** in a desktop browser.
2. Open DevTools (F12 or Cmd+Opt+I).
3. Go to the **Network** tab.
4. Refresh the page (or click any channel).
5. Filter for `api` in the requests list.
6. Click any request. In the **Headers** panel, find the
   `authorization:` header under Request Headers. That long string is your
   user token.

Treat this token like your password. Anyone with it can read/send/delete
on your account. **Never paste it into ChatGPT, Claude, Discord, or a
GitHub issue.** Put it directly into Railway's environment variables.

---

## Part 3 — Get the channel ID (1 min)

1. In Discord, go to **User Settings → Advanced → Developer Mode: ON**.
2. Right-click the channel (e.g. `#premium-alerts`) → **Copy Channel ID**.
3. Save that number. You can watch multiple channels by comma-separating.

---

## Part 4 — Deploy to Railway (10 min)

### Option A: Deploy from GitHub (recommended)

1. Create a new **private** GitHub repo.
2. Upload these files:
   - `bridge.py`
   - `requirements.txt`
   - `Procfile`
   - `.gitignore`
   - (do NOT upload `.env`)
3. Go to **railway.app**, sign in with GitHub.
4. **New Project → Deploy from GitHub repo** → pick your repo.
5. Once deployed, open the service → **Variables** tab → add:
   - `DISCORD_USER_TOKEN`
   - `CHANNEL_IDS`
   - `TWILIO_ACCOUNT_SID`
   - `TWILIO_AUTH_TOKEN`
   - `TWILIO_WHATSAPP_FROM` = `whatsapp:+14155238886`
   - `WHATSAPP_TO` = `whatsapp:+34XXXXXXXXX` (your real number)
   - `PREFIX_CHANNEL_NAME` = `true`
6. Railway auto-redeploys. Watch **Deployments → View Logs**. You should
   see `Connected as YourDiscordName`.
7. Post a test message in the target channel (from a second device or ask
   a friend, since your own messages are filtered out). WhatsApp should
   buzz within ~2 seconds.

### Option B: Deploy from CLI

```bash
npm i -g @railway/cli
railway login
cd discord-whatsapp-bridge
railway init
railway up
railway variables set DISCORD_USER_TOKEN=xxx CHANNEL_IDS=xxx ...
```

---

## Part 5 — Local testing (optional, recommended)

Before pushing to Railway, validate locally:

```bash
cd discord-whatsapp-bridge
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with your real values
set -a && source .env && set +a
python bridge.py
```

You should see connection logs. Post a test in the target channel → WhatsApp
arrives. Ctrl+C to stop. Then deploy to Railway for 24/7 operation.

---

## Cost breakdown

- **Railway:** free tier covers ~500 execution hours/month; this bot is
  ~1 process idling on a websocket, stays well inside free limits.
- **Twilio:** ~$0.005 per outbound WhatsApp message in the sandbox.
  Budget $1–5/month depending on signal volume.
- **Discord:** $0 (unless ban, see above).

---

## Troubleshooting

**No logs after deploy:** check that `DISCORD_USER_TOKEN` is correct.
Discord invalidates tokens if you change password.

**"Improper token has been passed":** you copied the token wrong, or
Discord rotated it. Re-extract it.

**Connects but no WhatsApp:** check Twilio logs in console. Most likely
the sandbox session expired — send any message to the sandbox number
from your WhatsApp and it reactivates.

**Messages arrive late:** check Railway region vs. your location.
Switch region in Railway settings if latency matters.

**Getting duplicate messages:** Railway might be running multiple replicas.
Ensure **Replicas: 1** in the service settings.

---

## Shutting it off

Railway → service → **Settings → Danger → Remove Service**. Or just pause
the deployment. Twilio keeps charging per message only when messages are
actually sent, so pausing the bot pauses the cost.
