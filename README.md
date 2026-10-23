# Mission MEDA

Your own Mindspace: five AI companions who share one memory and look after you.
Talk to them out loud in Telugu, English or Hindi (or all three mixed).

| | Agent | What they do |
|---|---|---|
| 🧑‍🎓 | **Sonu** | Your elder brother. Plans your day around classes and exams, tracks job and internship applications, and finds real ways to earn pocket money through open source (GSoC, LFX, Outreachy, bounties, sponsorships). Can search the web. |
| 🌸 | **Indu** | Health and mental support. Kind, funny, loyal, a little daring. Logs your mood, notices patterns, helps you calm down. |
| 🛠️ | **Lochu** | Your engineer. Opens your projects, reads code, debugs, runs tests, deploys, starts, restarts and stops processes, runs simulations. Uses your saved credentials without ever seeing them. **Every command waits for your Approve tap.** |
| 🔋 | **Jyothi** | The food pipe. Every request passes through her: she keeps the daily budget, cools down agents that run too hot, wakes them early, and watches your computer's CPU, memory, disk, battery and heat. |
| 🦁 | **Ramu** | For the hard, fast moments: anger, fights, sentimental waves, needing courage. Quick, steady, dashing. |
| 🔒 | **The lockbox** | Not an agent. Plain code rules nobody can talk around: no secrets in chat, no dangerous commands, nothing outside your projects folder, no action without your OK. |

## How it works

```
you (voice or text)
   │
   ▼
Router ── says a name? ("Indu, …") → that agent
   │      otherwise the AI picks the best fit
   ▼
Jyothi's gate ── budget left? agent cooling down?
   ▼
Agent (AI brain + its own personality and tools)
   │   ├── shared memory (facts, tasks, applications, moods)
   │   └── Lochu's tools ──► lockbox check ──► your Approve tap ──► runs
   ▼
reply shown on screen and spoken in that agent's voice
```

Everything runs on your own computer. Memory is one file: `data/meda.sqlite3`.

## Setup (about 10 minutes, no coding)

1. **Get a free Gemini key.** Open <https://aistudio.google.com/apikey>, sign in with your Google account,
   tap **Create API key**, and copy it. No card needed.

2. **Install Python** if you don't have it: <https://www.python.org/downloads/>.
   On Windows, tick **"Add python.exe to PATH"** on the first install screen.

3. **Download this project.** On the GitHub page, tap **Code → Download ZIP**, then unzip it somewhere easy, like Documents.

4. **Double-click the launcher:**
   - Windows: `Start Mission MEDA (Windows).bat`
   - Mac: `Start Mission MEDA (Mac).command` (the first time, right-click it and choose **Open**)

   The first run installs everything and asks a few questions: your Gemini key, your name, a passcode, and your
   projects folder. Then the app opens in your browser. Tap the 🎙️ mic, allow the microphone, and talk.

Keep the black window open while you use the crew. Close it to switch them off.

**Updating:** nothing to do. Each time you double-click the launcher, it fetches the newest version from GitHub
first, and never touches your `.env`, `vault.env` or `data` folder (your key, credentials and memory).

**Optional, credentials for Lochu:** copy `vault.env.example` to `vault.env` and add lines like `GITHUB_TOKEN=ghp_...`.
Lochu sees only the names and uses them in commands as `$GITHUB_TOKEN`. Values are hidden from anything the AI reads.

**For coders:** `pip install -r requirements.txt` then `python run.py`. All settings are in `.env` (see `.env.example`).

## Use it from your phone

Double-click `Start Mission MEDA on phone (Windows).bat` (Mac or terminal: `python run.py --phone`).
It prints an address like `https://192.168.1.5:8000`. Open it in Chrome on your phone (same Wi-Fi), tap
**Advanced → Proceed** on the certificate warning (it's your own home-made certificate), then enter your passcode.
Your laptop must stay on while you use it.

## Talking to the crew

- **Tap the mic** and speak. Pick the language you'll speak in from the top menu (తెలుగు is the default).
- **Hands-free** keeps listening after each reply, so you can have a back-and-forth conversation.
- **Say a name** first to call someone: "Sonu, ee roju plan enti?", "ఇందు, నాకు నిద్ర రావట్లేదు", "लोचू, server restart karo".
  Or tap an agent's face to talk only to them. "Auto" lets the crew decide.
- Replies come back in the language you used. Telugu gets a Telugu voice, Hindi a Hindi voice, English an Indian English voice.
- Code and commands appear on screen but aren't read aloud. Tap 🔈 on any message to hear it again.
- **The crew talks to each other.** Say **"everyone"**, **"అందరూ"** or **"सब"** and two or three of them
  answer in turn, building on each other like a huddle. Agents also consult each other on their own: Sonu might
  ask Indu about your sleep before planning exam week, and you'll see and hear Indu's answer to Sonu.
- **Board** shows Jyothi's health panel, your task list, applications and mood log.

**Voices:** the crew speaks with natural Microsoft neural voices (Telugu: Shruti and Mohan, Hindi: Swara and Madhur,
English: Neerja and Prabhat), fetched free over the internet by the app. Each agent gets a male or female voice with
its own speed and pitch. If those can't be reached, Google's Telugu/Hindi/English voice is the backup, and after that
your browser's own voices.

## What it costs

**Nothing, on the default setup.** The crew runs on Google's free Gemini tier (model `gemini-3.5-flash-lite`).
Voice is free too, because it uses your browser.

- Google's free tier has small per-model limits (for some models only about 20 requests a day). Mission MEDA spreads
  the load: when one free model is used up, it switches to the next free Gemini model on its own (Jyothi's Board shows
  which are ready and which are resting). Most messages use just one request, because keywords pick the agent for free
  and each agent consults a crewmate at most once per message.
- Jyothi also stops the crew at `MEDA_DAILY_REQUEST_LIMIT` (default 1500) as a safety cap.
- **Privacy:** Google may use free-tier chats to improve its products, and people may review them. Avoid sharing
  passwords, bank details or anything you'd never want read. Lochu's vault values never reach the AI either way.
- If Gemini says the model isn't found, open Google AI Studio, pick any free "Flash-Lite" or "Flash" model, and put
  its name in `.env` as `MEDA_MODEL=`.

**Want a smarter brain later?** Set `MEDA_PROVIDER=claude` and `ANTHROPIC_API_KEY=` in `.env`. Claude Opus 5.5 costs
about 2 to 4 US cents per message, and Jyothi then caps spending at `MEDA_DAILY_BUDGET_USD` (default $2). Paid
Claude API chats aren't used to train models by default.

## Safety

- The app only listens on your own computer unless you start it with `--phone`, which requires a passcode.
- Lochu cannot run anything until you tap **Approve**, and the lockbox refuses some commands even if you approve:
  wiping drives, `sudo`, piping downloads into a shell, shutting down, reading the vault.
- `.env`, `vault.env` and key files are never shown to any agent.
- Indu and Ramu share India's free 24x7 Tele-MANAS helpline (**14416**) and emergency number **112** if you ever say you're in danger.
- `.env`, `vault.env` and `data/` are in `.gitignore`, so they never get uploaded to GitHub.

## Files

| File | What's inside |
|---|---|
| `meda/agents.py` | Each agent's personality, tools and voice. Edit this to change how they behave. |
| `meda/router.py` | Picks which agent answers. |
| `meda/brain.py` | The Mindspace loop: gate, agent, tools, approvals. |
| `meda/providers.py` | The AI brains (Gemini and Claude) behind one simple interface. |
| `meda/voice.py` | Natural Telugu, Hindi and English voices. |
| `launch.py`, `update.py` | What the launchers run: self-update, install new parts, then start. |
| `meda/health.py` | Jyothi's budget, cooldowns and machine stats. |
| `meda/tools.py` | Every tool the agents can use. |
| `meda/lockbox.py` | The hard safety rules and the credential vault. |
| `meda/procs.py` | Running commands and background processes for Lochu. |
| `meda/memory.py` | Shared memory in SQLite. |
| `web/index.html` | The voice app. |
| `tests/` | Offline tests. Run `pip install pytest httpx` then `python -m pytest`. |

## Ideas for later

- A wake word ("Hey Sonu") so it listens without tapping.
- A Telegram bot so the crew can message you first (morning plan, exam reminders).
- Google Calendar sync for Sonu, and a fitness tracker link for Indu.
- More natural voices with a cloud text-to-speech service.
