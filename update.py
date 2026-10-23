"""Self-updater: fetches the newest Mission MEDA from GitHub before each start.

Your own files are never touched: .env, vault.env, the data folder (memory),
.venv, and the launcher scripts. If there's no internet or GitHub can't be
reached, it just starts the version you already have.
"""

import io
import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEEP = {".env", "vault.env", "data", ".venv", ".git"}
KEEP_SUFFIXES = (".bat", ".command")  # a running launcher must not be rewritten under itself
VERSION_FILE = ROOT / "data" / "version.txt"


def repo() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("MEDA_UPDATE_REPO="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("MEDA_UPDATE_REPO", "sainihalmeda-ai/mission_meda")


def fetch(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mission-meda-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def protected(rel: Path) -> bool:
    return rel.parts[0] in KEEP or rel.name.endswith(KEEP_SUFFIXES)


def update() -> None:
    name = repo()
    if not name or name.lower() == "off":
        return
    try:
        latest = json.loads(fetch(f"https://api.github.com/repos/{name}/commits/main"))["sha"]
    except Exception as e:
        print(f"  (Couldn't check for updates: {type(e).__name__}. Starting the current version.)")
        return
    current = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else ""
    if latest == current:
        print("  Mission MEDA is up to date.")
        return
    print("  Updating Mission MEDA to the newest version...")
    try:
        archive = zipfile.ZipFile(io.BytesIO(fetch(f"https://codeload.github.com/{name}/zip/{latest}", 120)))
    except Exception as e:
        print(f"  (Update download failed: {type(e).__name__}. Starting the current version.)")
        return
    changed = 0
    for info in archive.infolist():
        parts = Path(info.filename).parts[1:]  # drop the "mission_meda-<sha>/" folder
        if info.is_dir() or not parts:
            continue
        rel = Path(*parts)
        if protected(rel):
            continue
        target = ROOT / rel
        data = archive.read(info)
        if target.exists() and target.read_bytes() == data:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".new")
        tmp.write_bytes(data)
        shutil.move(str(tmp), str(target))
        changed += 1
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(latest)
    print(f"  Updated {changed} file(s). Your key, memory and settings were kept.")


if __name__ == "__main__":
    update()
