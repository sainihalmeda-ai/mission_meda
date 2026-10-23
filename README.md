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
   │      otherwise Claude picks the best fit
   ▼
Jyothi's gate ── budget left? agent cooling down?
   ▼
Agent (Claude Opus 5.5 + its own personality and tools)
   │   ├── shared memory (facts, tasks, applications, moods)
   │   └── Lochu's tools ──► lockbox check ──► your Approve tap ──► runs
   ▼
reply shown on screen and spoken in that agent's voice
```

Everything runs on your own computer. Memory is one file: `data/meda.sqlite3`.

## Setup (about 10 minutes, no coding)

1. **Get a Claude API key.** Sign in at <https://platform.claude.com>, add a little credit (about $5 lasts a long time),
   and create a key under **API keys**. Copy it.

2. **Install Python** if you don't have it: <https://www.python.org/downloads/>.
   On Windows, tick **"Add python.exe to PATH"** on the first install screen.

3. **Download this project.** On the GitHub page, tap **Code → Download ZIP**, then unzip it somewhere easy, like Documents.

4. **Double-click the launcher:**
   - Windows: `Start Mission MEDA (Windows).bat`
   - Mac: `Start Mission MEDA (Mac).command` (the first time, right-click it and choose **Open**)

   The first run installs everything and asks a few questions: your API key, your name, a passcode, and your
   projects folder. Then the app opens in your browser. Tap the 🎙️ mic, allow the microphone, and talk.

Keep the black window open while you use the crew. Close it to switch them off.

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
- Code and commands appear on screen but aren't read aloud.
- **Board** shows Jyothi's health panel, your task list, applications and mood log.

**Telugu voice missing?** Speaking depends on voices your device has.
- Android Chrome: has Google తెలుగు built in.
- Windows: Edge has natural Telugu and Hindi voices. Or add them in Settings → Time & language → Speech → Add voices.
- Mac: System Settings → Accessibility → Spoken Content → System voice → Manage voices → add Telugu and Hindi.

## What it costs

Each message costs roughly 2 to 4 US cents with Claude Opus 5.5. Jyothi stops the crew when today's spend reaches
`MEDA_DAILY_BUDGET_USD` (default $2.00) and cools down any agent that uses more than `MEDA_AGENT_TOKENS_PER_HOUR`
in an hour. Ask "Jyothi, how is everyone?" any time.

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
