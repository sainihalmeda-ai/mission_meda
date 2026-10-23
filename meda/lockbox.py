"""The Ultron lockbox: hard rules that no agent can talk its way around.

The AI never decides these. Plain Python code enforces them:
  * Credentials live in vault.env. Agents only ever see the names, never the values.
  * Every command Lochu wants to run waits for your tap on "Approve".
  * Commands only run inside your projects folder.
  * Commands that could wreck your machine are blocked outright, even if you approve.
  * Secret values are scrubbed out of any output before an agent reads it.
"""

import re
from pathlib import Path

from . import config

# Patterns that are never allowed, approval or not.
BLOCKED_PATTERNS = [
    (r"\brm\s+(-[a-zA-Z]*\s+)*(/|~|\$HOME)(\s|$)", "deleting your whole drive or home folder"),
    (r"\bmkfs(\.\w+)?\b", "formatting a disk"),
    (r"\bdd\s+.*of=/dev/", "writing raw data to a disk"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "a fork bomb"),
    (r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b", "shutting down the computer"),
    (r"\bchmod\s+-R\s+777\s+/", "opening up permissions on the whole system"),
    (r"(curl|wget)[^|]*\|\s*(sudo\s+)?(ba|z)?sh\b", "piping a download straight into a shell"),
    (r"\bformat\s+[a-zA-Z]:", "formatting a Windows drive"),
    (r"\b(del|rd|rmdir)\s+/s\s+.*[a-zA-Z]:\\\s*$", "deleting a whole Windows drive"),
    (r"\bcat\b.*vault\.env|\btype\b.*vault\.env", "reading the credential vault"),
    (r"\b(printenv|env)\s*$|\bset\s*$", "dumping every environment variable"),
]


def check_command(command: str) -> str | None:
    """Return a reason string if the command is forbidden, otherwise None."""
    for pattern, why in BLOCKED_PATTERNS:
        if re.search(pattern, command, flags=re.IGNORECASE):
            return f"Blocked by the lockbox: this looks like {why}."
    if "sudo " in command or command.strip().startswith("sudo"):
        return "Blocked by the lockbox: Lochu never runs commands as administrator (sudo). Run it yourself if you really need to."
    return None


def safe_path(relative: str) -> Path:
    """Resolve a path and make sure it stays inside the projects folder."""
    base = config.PROJECTS_DIR
    target = (base / relative).resolve() if relative else base
    if target != base and base not in target.parents:
        raise PermissionError(f"Lockbox: Lochu can only work inside {base}.")
    return target


# ---------- credential vault ----------

def load_vault() -> dict[str, str]:
    """Read NAME=value pairs from vault.env. Values never leave this module except into a subprocess."""
    vault: dict[str, str] = {}
    path = config.VAULT_PATH
    if not path.exists():
        return vault
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        vault[key.strip()] = value.strip().strip('"').strip("'")
    return vault


def credential_names() -> list[str]:
    return sorted(load_vault().keys())


def scrub(text: str) -> str:
    """Replace any secret value that shows up in output with its name."""
    for name, value in load_vault().items():
        if value and len(value) >= 4:
            text = text.replace(value, f"[{name} hidden]")
    return text
