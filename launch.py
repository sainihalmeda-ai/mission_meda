"""What the double-click launchers run: update, install anything new, then start."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    try:
        import update
        update.update()
    except Exception as e:  # an updater problem must never stop the crew from starting
        print(f"  (Skipped update: {type(e).__name__}: {e})")
    print("  Checking parts...")
    subprocess.call([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                     "-r", str(ROOT / "requirements.txt")])
    # Start the app in a fresh process so freshly updated code is the code that runs.
    sys.exit(subprocess.call([sys.executable, str(ROOT / "run.py"), *sys.argv[1:]]))


if __name__ == "__main__":
    main()
