"""Settings for Mission MEDA, read from the .env file (or real environment variables)."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader so beginners don't need an extra package."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

# Your name, so the crew knows who they are looking after.
OWNER_NAME = os.environ.get("MEDA_OWNER_NAME", "Sai")

# The Claude model every agent uses. Opus 5.5 is the current default.
MODEL = os.environ.get("MEDA_MODEL", "claude-opus-5-5")

# Passcode the web app asks for. Lochu can run commands on your computer,
# so never expose the app without one.
PASSCODE = os.environ.get("MEDA_PASSCODE", "")

# Folder that holds your coding projects. Lochu can only read and run inside it.
PROJECTS_DIR = Path(os.path.expanduser(os.environ.get("MEDA_PROJECTS_DIR", "~/projects"))).resolve()

# Where memory (facts, tasks, moods, chat history) is stored.
DATA_DIR = Path(os.path.expanduser(os.environ.get("MEDA_DATA_DIR", str(ROOT / "data")))).resolve()
DB_PATH = DATA_DIR / "meda.sqlite3"

# Lochu's credential vault: a separate file the AI never reads directly.
VAULT_PATH = Path(os.path.expanduser(os.environ.get("MEDA_VAULT", str(ROOT / "vault.env")))).resolve()

# Jyothi's limits. Daily spend cap in US dollars, and per-agent tokens per hour
# before that agent is sent to cool down.
DAILY_BUDGET_USD = float(os.environ.get("MEDA_DAILY_BUDGET_USD", "2.00"))
AGENT_TOKENS_PER_HOUR = int(os.environ.get("MEDA_AGENT_TOKENS_PER_HOUR", "200000"))
COOLDOWN_MINUTES = int(os.environ.get("MEDA_COOLDOWN_MINUTES", "10"))

# Price per million tokens for the model above (input, output), used for the budget.
PRICE_IN = float(os.environ.get("MEDA_PRICE_IN", "4.00"))
PRICE_OUT = float(os.environ.get("MEDA_PRICE_OUT", "20.00"))

# A conversation room is restarted after this many messages; memory carries over.
MAX_ROOM_MESSAGES = int(os.environ.get("MEDA_MAX_ROOM_MESSAGES", "80"))
