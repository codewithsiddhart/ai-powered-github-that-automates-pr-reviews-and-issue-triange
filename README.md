# 🤖 GitHub Autopilot

> A self-hosted, AI-powered GitHub assistant that reviews pull requests, triages issues, scans for leaked secrets, and answers 26 slash commands like `/fix` and `/autofix` — running entirely on free-tier infrastructure ($0/month).

**Crafted by Siddharth Purohit & Shweta Sharma.**

- **Web framework:** Flask (entry point: `server.py`)
- **AI:** 4-provider router (Groq 70B, Groq 8B, Gemini Flash, OpenRouter) with automatic failover
- **State:** Redis (with in-memory fallback)
- **Deploy target:** Render (free tier)

For deep architecture details, see [`docs/architecture/system-architecture.md`](docs/architecture/system-architecture.md). A full visual project guide is also available as `GitHub-Autopilot-Project-Guide.pdf` in the repo root.

---
---

# 📦 DEPLOYMENT & SETUP GUIDE (The Human Side)

> **Read this if you have finished the code and now need to actually run and deploy it.**
> This guide assumes you know basic Git and Python but have **never deployed this kind of project before.** Every external step is spelled out. Follow it top to bottom.

## 🗺️ What you're about to set up (the big picture)

This project is a **GitHub App**. That means it's not a normal website you just visit — it's a server that **GitHub talks to.** Here's the chain you are building:

```
   YOU set up 3 things:                  THEY connect like this:

   1. A GitHub App  ───────────────────►  sends webhooks to your server
   2. A server on Render  ◄────────────►  runs your Flask code (server.py)
   3. A Redis database  ◄──────────────►  stores state for the server
                          
   Plus: AI API keys (Groq) so the server can think.
```

So your job, in order, is:
1. Get all your **accounts & credentials** ready (GitHub App, Groq, etc.).
2. Deploy the **server + Redis** on Render.
3. Point the **GitHub App's webhook** at your deployed server.
4. **Install** the GitHub App on a repo and test it.

There are **5 external accounts** you'll need (all free):

| Service | Why you need it | Free? |
|---------|-----------------|-------|
| **GitHub** | The App itself + the repos it manages | ✅ Yes |
| **Render** | Hosts your Flask server + Redis | ✅ Yes (free tier) |
| **Groq** | The AI brain (mandatory) | ✅ Yes |
| **Google AI Studio (Gemini)** | Backup AI brain (optional) | ✅ Yes |
| **OpenRouter** | Emergency backup AI (optional) | ✅ Yes |

---

## 1. 💻 Local Setup

You can run the whole thing on your own computer first to make sure it works, before deploying.

### 1.1 — Software you need installed

| Software | Version | How to check | How to install |
|----------|---------|--------------|----------------|
| **Python** | 3.11 or 3.12 (recommended) | `python3 --version` | [python.org/downloads](https://www.python.org/downloads/) |
| **pip** | (comes with Python) | `pip --version` | included with Python |
| **Git** | any recent | `git --version` | [git-scm.com](https://git-scm.com/) |
| **Redis** | 6+ | `redis-cli --version` | see §5 below |

> ⚠️ **Python version note:** This project pins libraries like `sentence-transformers` and `qdrant-client` that may not yet support the very newest Python (e.g. 3.14). If `pip install` fails, use **Python 3.11 or 3.12**. The included `Dockerfile` uses `python:3.11-slim`, so 3.11 is the safest choice.

### 1.2 — Install dependencies

Open a terminal **in the project folder** (`github-autopilot-main`) and run:

```bash
# 1. (Recommended) create an isolated virtual environment
python3 -m venv venv

# 2. activate it
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows (PowerShell)

# 3. install all required packages
pip install -r requirements.txt
```

**What this does:** creates a clean Python sandbox just for this project, then installs Flask, the Groq SDK, Redis client, and everything else listed in [`requirements.txt`](requirements.txt).

**Expected output:** a long list ending in `Successfully installed flask-3.1.1 ...` with no red `ERROR` lines.

### 1.3 — Create your `.env` file

The project reads its secrets from environment variables. There's a template already in the repo: [`.env.example`](.env.example). Copy it:

```bash
cp .env.example .env
```

Now open `.env` in your editor and fill in the values. **(How to get each value is explained in §2, §3, §4.)** Don't worry about getting them all yet — for a first local test you only strictly need `GITHUB_WEBHOOK_SECRET` and `GROQ_API_KEY`.

> 🔒 **`.env` is already in `.gitignore`** — it will never be committed. Never paste real secrets anywhere public.

### 1.4 — Start the project

```bash
python3 server.py
```

**What this does:** starts the Flask development server on port 5000. On boot it runs `startup_check()`, which **refuses to start if `GITHUB_WEBHOOK_SECRET` is missing** (this is a deliberate security feature called "fail-closed").

**Expected output:**
```
 * Running on http://0.0.0.0:5000
```

### 1.5 — Verify it's working

Open a **second terminal** and run:

```bash
curl http://localhost:5000/ping
```

**Expected output:**
```json
{"status": "ok", "version": "4.2.0"}
```

✅ If you see that, your server runs. You can also open **http://localhost:5000/** in a browser to see the landing page, and **http://localhost:5000/dashboard** for the live dashboard.

---

## 2. 🔑 Environment Variables

Every variable lives in your `.env` file locally (and in Render's dashboard when deployed). Here is every single one:

### Mandatory (the app won't work without these)

| Variable | What it does | How to get it |
|----------|--------------|---------------|
| `GITHUB_APP_ID` | The numeric ID of your GitHub App, so it can authenticate. | §3, Step 7 |
| `GITHUB_PRIVATE_KEY` | The App's private RSA key — used to sign authentication tokens. | §3, Step 8 |
| `GITHUB_WEBHOOK_SECRET` | A secret string GitHub and your server share, to prove webhooks are genuine. | You invent it — see below |
| `GROQ_API_KEY` | The key for the main AI brain (Groq / Llama). | §4.1 |
| `REDIS_URL` | Connection string for Redis (state storage). | §5 |

**How to create `GITHUB_WEBHOOK_SECRET`:** it's just a random string you make up. Generate a strong one:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Copy the output. You'll paste the **same value** into two places: your `.env` and the GitHub App settings (§3, Step 6).

> ⚠️ **About `GITHUB_PRIVATE_KEY` formatting:** the code converts literal `\n` into real newlines (`auth.py` does `.replace("\\n", "\n")`). So in your `.env`, put the whole key on **one line** with `\n` where the line breaks are, wrapped in quotes:
> ```
> GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIB...\n...\n-----END RSA PRIVATE KEY-----"
> ```

### Optional (nice to have, app works without them)

| Variable | What it does | Default if missing |
|----------|--------------|--------------------|
| `GEMINI_API_KEY` | Adds Google Gemini as a backup AI (good for long files). | Skipped — Groq only |
| `OPENROUTER_API_KEY` | Adds OpenRouter as an emergency backup AI. | Skipped |
| `DISCORD_WEBHOOK_URL` | Lets `/notify` and alerts post to Discord. | Notifications off |
| `SLACK_WEBHOOK_URL` | Same, for Slack. | Notifications off |
| `METRICS_AUTH_TOKEN` | Password-protects `/health` and `/metrics`. If unset, they're open. | Endpoints public |
| `MAX_DISPATCH_WORKERS` | How many background threads process events. | `6` |
| `REPO_DAILY_AI_LIMIT` | Max AI calls per repo per day (cost guard). | `150` |
| `STALE_ISSUE_DAYS` | How old an issue must be to count as "stale". | `30` |

---

## 3. 🐙 GitHub App Setup (from scratch)

This is the most involved part. Take it slowly. A **GitHub App** is GitHub's official way to build integrations.

### Step 1 — Open the App creation page
Go to **GitHub → your profile photo (top-right) → Settings → Developer settings → GitHub Apps → New GitHub App.**
Direct link: **https://github.com/settings/apps/new**

> 💡 To make an App for an **organization** instead of your personal account, go to the org's Settings → Developer settings → GitHub Apps → New GitHub App.

### Step 2 — Basic details
- **GitHub App name:** anything unique, e.g. `my-github-autopilot`.
- **Homepage URL:** your future Render URL (you can use `https://example.com` for now and change it later). After deploying it'll be something like `https://github-autopilot-1.onrender.com`.
- **Description:** optional, e.g. "AI-powered repo assistant."

### Step 3 — Callback URL
- **Leave it blank.** This project does **not** use OAuth user-login, so you don't need a callback URL, Client ID, or Client Secret for the core features.

> ℹ️ You'll see "Client ID" and "Client secret" on the App page after creation. **This project doesn't use them** — they're only for "Sign in with GitHub" flows, which this app doesn't do. You can ignore them.

### Step 4 — Webhook
- ✅ **Check "Active".**
- **Webhook URL:** this is where GitHub sends events. It must end in `/webhook`.
  - For now, if you haven't deployed yet, put a placeholder like `https://example.com/webhook` and **come back to fix it after Render gives you a URL** (§7).
  - Final value will be: `https://YOUR-RENDER-APP.onrender.com/webhook`

### Step 5 — Webhook secret
- Paste the **same random string** you generated for `GITHUB_WEBHOOK_SECRET` in §2.
- ⚠️ This is the #1 source of "401 Unauthorized" errors later. The value here and in your env **must match exactly.**

### Step 6 — Permissions
Scroll to **Repository permissions** and set these (this app needs them for its features):

| Permission | Access | Why |
|------------|--------|-----|
| **Contents** | Read & write | Read files, create branches/commits for `/autofix` |
| **Issues** | Read & write | Triage, comment, label, create security issues |
| **Pull requests** | Read & write | Review, summarize, comment, merge, edit titles |
| **Metadata** | Read-only | (Mandatory, auto-selected) basic repo info |
| **Actions** | Read & write | `/runtests` (trigger workflows), `/ci` analysis |
| **Checks** | Read-only | Read CI check results for `/merge` guardrails |
| **Administration** | Read-only | Collaborator permission checks for `/merge`, `/rollback` |

> 💡 If you don't need a feature, you can give less — but the above covers everything. **Less permission = some commands silently fail with 403.**

### Step 7 — Subscribe to webhook events
Scroll to **Subscribe to events** and check these boxes:

- ✅ **Pull request**
- ✅ **Issues**
- ✅ **Issue comment** (this is what powers all the `/slash` commands!)
- ✅ **Push**
- ✅ **Check run** (for CI analysis)

> ⚠️ **Common mistake:** forgetting **Issue comment**. Without it, none of your slash commands (`/fix`, `/autofix`, etc.) will ever fire.

### Step 8 — Where the App can be installed
- Choose **"Only on this account"** (simplest for a hackathon) or "Any account" if you want others to install it.

### Step 9 — Create the App
Click **Create GitHub App.** 🎉 You now have an App.

### Step 10 — Grab your App ID
On the App's settings page (the "General" tab), near the top you'll see **App ID:** a number like `123456`.
→ This is your `GITHUB_APP_ID`.

### Step 11 — Generate the private key
On the same page, scroll to **Private keys** → click **Generate a private key.**
- A `.pem` file downloads to your computer. **Keep it safe — you can't re-download it.**
- Open it in a text editor. Its contents (starting with `-----BEGIN RSA PRIVATE KEY-----`) are your `GITHUB_PRIVATE_KEY`.
- To put it in `.env` as a single line, convert newlines to `\n` (see the formatting note in §2). Quick helper:
  ```bash
  awk '{printf "%s\\n", $0}' your-key.pem
  ```
  Copy that output between quotes into `GITHUB_PRIVATE_KEY`.

### Step 12 — Install the App on a repository
On the App's settings page, click **Install App** (left sidebar) → choose your account → select **"Only select repositories"** → pick a test repo → **Install.**

✅ The App is now live on that repo. The moment you finish §7 (deploy) and fix the webhook URL, events from that repo will start flowing.

### Common GitHub App mistakes
- ❌ Webhook secret mismatch → every webhook returns 401. **Fix:** make the values identical.
- ❌ Forgot to subscribe to "Issue comment" → slash commands don't work.
- ❌ Webhook URL missing `/webhook` at the end → 404s.
- ❌ Installed the App but on the wrong repo → no events. Re-check "Install App".
- ❌ Private key newlines broken in `.env` → "Could not deserialize key" errors. Use the `\n` format.

---

## 4. 🧠 API Keys & External Services

### 4.1 — Groq (MANDATORY — the main AI brain)
- **Why:** runs Llama 3.3 70B and 3.1 8B — the models that write reviews, fixes, summaries.
- **Free tier:** ✅ Yes, generous (5,000 + 12,000 requests/day).
- **Where to get it:**
  1. Go to **https://console.groq.com**
  2. Sign up / log in.
  3. Click **API Keys** (left sidebar) → **Create API Key.**
  4. Copy the key (starts with `gsk_...`).
- **Configure:** paste into `GROQ_API_KEY` in `.env` (and later in Render).

### 4.2 — Google Gemini (OPTIONAL — backup for long files)
- **Why:** 1-million-token context window; used as a fallback for very large inputs.
- **Free tier:** ✅ Yes.
- **Where:** **https://aistudio.google.com/app/apikey** → **Create API key** → copy (starts with `AIza...`).
- **Configure:** `GEMINI_API_KEY` in `.env`.

### 4.3 — OpenRouter (OPTIONAL — emergency backup)
- **Why:** last-resort AI provider if Groq and Gemini are both down.
- **Free tier:** ✅ Yes (limited).
- **Where:** **https://openrouter.ai/keys** → **Create Key** → copy (starts with `sk-or-...`).
- **Configure:** `OPENROUTER_API_KEY` in `.env`.

### 4.4 — Discord / Slack (OPTIONAL — notifications)
- **Why:** so `/notify` and security alerts can ping a channel.
- **Discord:** in your server → **Server Settings → Integrations → Webhooks → New Webhook → Copy URL.** Put in `DISCORD_WEBHOOK_URL`.
- **Slack:** **https://api.slack.com/messaging/webhooks** → create an incoming webhook → copy URL. Put in `SLACK_WEBHOOK_URL`.

> 💡 You can skip everything in §4.2–4.4 for a first deployment. Only **Groq (§4.1)** is required.

---

## 5. 🗄️ Redis Setup

Redis stores all shared state: deduplication keys, rate limits, AI usage counters, analytics, and rollback snapshots.

> ℹ️ **Good news:** if Redis is missing, the app uses an in-memory fallback and keeps working (it just loses dedup across restarts). But for real deployment you **want** Redis.

### Option A — Local Redis (for local testing)

**Linux:**
```bash
sudo apt install redis-server        # Debian/Ubuntu
# or: sudo pacman -S redis            # Arch
sudo systemctl start redis
```
**macOS:**
```bash
brew install redis
brew services start redis
```
**Any OS via Docker:**
```bash
docker run -d -p 6379:6379 redis
```

Then in `.env`:
```
REDIS_URL=redis://localhost:6379/0
```

**Verify it works:**
```bash
redis-cli ping
```
Expected output: `PONG` ✅

### Option B — Cloud Redis (for Render deployment)
You **don't create this manually** — the included [`render.yaml`](render.yaml) defines a free Redis service and wires its connection string into your web service automatically (§7). If you deploy manually instead of via the blueprint, see §7.4.

---

## 6. ▶️ Running Locally (every command, in order)

```bash
# 1. Go to the project folder
cd github-autopilot-main

# 2. Activate your virtual environment
source venv/bin/activate

# 3. Make sure Redis is running (separate terminal or as a service)
redis-cli ping            # should print PONG

# 4. Confirm your .env is filled (at minimum: GITHUB_WEBHOOK_SECRET + GROQ_API_KEY)

# 5. Start the server
python3 server.py
```

**Expected:** `Running on http://0.0.0.0:5000`

**In another terminal, verify:**
```bash
curl http://localhost:5000/ping            # → {"status":"ok",...}
curl http://localhost:5000/api/dashboard   # → JSON with metrics (mock data if unconfigured)
```

> 💡 **GitHub can't reach `localhost`.** To test real webhooks locally, use a tunnel like [ngrok](https://ngrok.com): run `ngrok http 5000`, then temporarily set your GitHub App's webhook URL to the `https://....ngrok.io/webhook` address it gives you. For most people it's easier to just deploy to Render (§7) and test there.

To run the **production server command** locally (same as Render uses):
```bash
gunicorn server:app --workers 1 --threads 8 --bind 0.0.0.0:5000
```

---

## 7. 🚀 Deploying to Render

There are two ways. **Option A (Blueprint) is by far the easiest** because [`render.yaml`](render.yaml) already defines everything.

### Option A — Deploy with the Blueprint (recommended)

**Step 1 — Push your code to GitHub**
Your code must be in a GitHub repo Render can read:
```bash
git add .
git commit -m "Deploy GitHub Autopilot"
git push
```

**Step 2 — Create a Render account**
Go to **https://render.com** → **Sign up** → choose **"Sign in with GitHub"** (easiest, so Render can see your repos).

**Step 3 — New Blueprint**
- In the Render dashboard, click **New +** (top right) → **Blueprint.**
- Select the repository containing this project.
- Render reads `render.yaml` and shows you **two services** to create: a **web service** (`github-autopilot-1`) and a **Redis** (`github-autopilot-redis`).
- Click **Apply.**

**Step 4 — Fill in environment variables**
Render will prompt you for the variables marked `sync: false` in `render.yaml` (it can't know your secrets). Enter:
- `GITHUB_APP_ID`
- `GITHUB_PRIVATE_KEY` (the `\n`-formatted one-line version)
- `GITHUB_WEBHOOK_SECRET`
- `GROQ_API_KEY`
- (optional) `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DISCORD_WEBHOOK_URL`, `SLACK_WEBHOOK_URL`, `METRICS_AUTH_TOKEN`

> ✅ `REDIS_URL` is filled **automatically** by the blueprint — don't touch it.

**Step 5 — Deploy**
Click **Create / Apply.** Render runs the **build command** (`pip install -r requirements.txt`) then the **start command** (gunicorn). Watch the **Logs** tab. First build takes a few minutes (it downloads ML libraries).

**Step 6 — Get your URL**
When the web service shows **"Live"**, copy its URL at the top — e.g. `https://github-autopilot-1.onrender.com`.

**Step 7 — Point the GitHub App webhook at it** ⬅️ *don't skip this!*
- Go back to your **GitHub App settings** → **General** → **Webhook URL.**
- Set it to: `https://github-autopilot-1.onrender.com/webhook`
- Also update the **Homepage URL** to your Render URL while you're there.
- Click **Save changes.**

**Step 8 — Verify**
```bash
curl https://github-autopilot-1.onrender.com/ping
```
Expected: `{"status":"ok","version":"4.2.0"}` ✅

### Option B — Manual web service (if you don't use the blueprint)

1. **New + → Web Service** → connect your repo.
2. **Branch:** `main` (or whichever you deploy).
3. **Runtime:** Python.
4. **Build Command:** `pip install -r requirements.txt`
5. **Start Command:**
   ```
   gunicorn server:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:$PORT --worker-class gthread
   ```
6. **Health Check Path:** `/ping`
7. **Plan:** Free.
8. Add all environment variables manually under the **Environment** tab.
9. **Redis:** click **New + → Redis** (free plan), then copy its **Internal Connection String** into a `REDIS_URL` env var on your web service.

### Render housekeeping

| Task | Where to click |
|------|----------------|
| **View logs** | Your service → **Logs** tab (live tail) |
| **Redeploy** | Service → **Manual Deploy** → **Deploy latest commit** |
| **Update after code changes** | Just `git push` — Render auto-deploys on push |
| **Change env vars** | Service → **Environment** → edit → save (triggers redeploy) |
| **Custom domain** | Service → **Settings** → **Custom Domains** |
| **Health check** | Already set to `/ping` in `render.yaml` |

> ⚠️ **Free-tier sleep:** Render free web services **sleep after ~15 min of inactivity** and take ~30–60s to wake on the next request. The first webhook after sleeping may be slow, but GitHub retries, so events aren't lost. For a live hackathon demo, hit `/ping` a minute before presenting to wake it up.

> ⚠️ **Memory:** the free tier has 512MB RAM. The `sentence-transformers` library is heavy. If you hit out-of-memory errors on boot, the embedding/RAG features degrade gracefully (they're optional) — the core bot still runs.

---

## 8. ✅ Testing Every Feature

After deploying, test in this order:

### 8.1 — Health endpoints (fastest sanity check)
```bash
curl https://YOUR-APP.onrender.com/ping       # public, always works
curl https://YOUR-APP.onrender.com/api/dashboard
# If you set METRICS_AUTH_TOKEN:
curl -H "Authorization: Bearer YOUR_TOKEN" https://YOUR-APP.onrender.com/health
```

### 8.2 — Webhook delivery (is GitHub reaching you?)
- Go to **GitHub App settings → Advanced** tab.
- Scroll to **Recent Deliveries.** Every webhook GitHub sends is listed.
- A green ✅ check = delivered and your server replied 2xx. A red ❌ = problem (click it to see the response — usually 401 from a secret mismatch).
- You can click **Redeliver** on any event to retry it.

### 8.3 — Issue events
- Open a **new issue** in your test repo.
- Within a few seconds the bot should comment with a triage (type, priority, labels, a welcome message).

### 8.4 — Pull Request events
- Open a **pull request.**
- The bot should post a **PR summary**, an **AI code review**, and a **test-gap analysis.**

### 8.5 — Slash commands / AI responses
- On any issue or PR, comment: `/explain` followed by a code snippet, or just `/health`.
- The bot should reply. Try `/fix`, `/improve`, `/autofix` on an issue.
- ✅ This confirms your **Groq API key** is working (AI responses) **and** the **Issue comment** webhook is subscribed.

### 8.6 — Push events
- Push a commit to `main` with a non-conventional message (like `updated stuff`). After 3+ such commits the bot opens a commit-convention issue.
- Push a file containing a fake-looking secret (e.g. `AKIAIOSFODNN7EXAMPLE`) → the bot opens a 🚨 security issue.

### 8.7 — Logs
- Render → your service → **Logs.** You'll see lines like:
  ```
  webhook.received event=issues repo=you/test ...
  dispatch.start event=issues ...
  router.call task=issue_triage provider=groq_70b tokens=...
  dispatch.done event=issues
  ```

---

## 9. 🛠️ Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Server won't start: `RuntimeError` about webhook secret | `GITHUB_WEBHOOK_SECRET` not set | Set it in `.env` / Render env. This is the fail-closed guard. |
| Webhooks show **401** in Recent Deliveries | Secret mismatch | Make the GitHub App webhook secret **identical** to `GITHUB_WEBHOOK_SECRET`. |
| Webhooks show **404** | Wrong webhook URL | Must be `https://your-app.onrender.com/webhook` (note the `/webhook`). |
| Bot never responds to comments | "Issue comment" event not subscribed | GitHub App → Permissions & events → check **Issue comment**. |
| `Could not deserialize key data` | Private key newlines broken | Use the `\n` single-line format (§2 / §3 Step 11). |
| Commands return "AI temporarily unavailable" | Groq key missing/invalid, or quota hit | Check `GROQ_API_KEY`; check Groq console usage. |
| 403 errors on `/merge`, `/runtests` | App missing permissions | Grant Actions/Administration permissions (§3 Step 6), then **re-install** the App. |
| `/report`, `/budget` say data unavailable | Redis not connected | Check `REDIS_URL`; in Render confirm the Redis service is "Available". |
| First request after idle is very slow | Free-tier sleep | Normal. Hit `/ping` to wake it; GitHub auto-retries. |
| Build fails on `pip install` | Python version too new | Use Python 3.11/3.12 locally; Render uses a compatible runtime. |
| Out-of-memory on Render boot | 512MB limit + heavy ML libs | RAG features degrade gracefully; core bot still works. Consider removing `sentence-transformers`/`qdrant-client` from `requirements.txt` if you don't use embeddings. |

> 🔍 **Golden rule:** when something doesn't work, check **two places in order** — (1) GitHub App → **Advanced → Recent Deliveries** (did GitHub reach you, and what status came back?), and (2) Render → **Logs** (what did your server do?). 90% of problems are diagnosed there.

---

## 10. 📋 Final Pre-Submission Checklist

Tick every box before you demo or submit:

**Accounts & credentials**
- [ ] GitHub App created
- [ ] App ID copied into `GITHUB_APP_ID`
- [ ] Private key generated and formatted into `GITHUB_PRIVATE_KEY`
- [ ] Webhook secret generated and set in **both** GitHub App **and** `GITHUB_WEBHOOK_SECRET`
- [ ] Groq API key obtained and set in `GROQ_API_KEY`

**GitHub App config**
- [ ] Permissions set: Contents, Issues, Pull requests, Metadata, Actions, Checks, Administration
- [ ] Events subscribed: Pull request, Issues, **Issue comment**, Push, Check run
- [ ] App **installed** on at least one test repository

**Deployment**
- [ ] Code pushed to GitHub
- [ ] Render web service is **Live**
- [ ] Render Redis service is **Available**
- [ ] All env vars entered in Render
- [ ] Webhook URL in GitHub App updated to the live Render URL + `/webhook`
- [ ] Homepage URL updated to the Render URL

**Verification**
- [ ] `/ping` returns `{"status":"ok"}`
- [ ] Landing page (`/`) and dashboard (`/dashboard`) load
- [ ] Recent Deliveries show green ✅
- [ ] Opening an issue triggers a triage comment
- [ ] Opening a PR triggers a review comment
- [ ] A slash command (`/health` or `/explain`) gets a reply
- [ ] (Optional) wake the service with `/ping` right before your demo

**You're ready. Go win that hackathon. 🚀**

---

### Quick reference

| Thing | Value |
|-------|-------|
| Entry point | `server.py` (Flask app object: `app`) |
| Start command | `gunicorn server:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT --worker-class gthread` |
| Webhook path | `/webhook` |
| Health (public) | `/ping` |
| Health (detailed, token-gated) | `/health` |
| Metrics (token-gated) | `/metrics` |
| Per-repo config file | `.ai-repo-manager.yml` (place in each managed repo's root) |
| Env template | `.env.example` |
| Deploy config | `render.yaml` |
