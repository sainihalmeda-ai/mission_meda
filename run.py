"""Start Mission MEDA.

    python run.py            # laptop only: open http://localhost:8000
    python run.py --phone    # also reachable from your phone on the same Wi-Fi (HTTPS, needs a passcode)
"""

import argparse
import getpass
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def first_run_setup() -> None:
    """Ask for the API key, name and passcode the first time, and write them to .env."""
    env = ROOT / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else (ROOT / ".env.example").read_text(encoding="utf-8")
    values = dict(l.split("=", 1) for l in text.splitlines() if "=" in l and not l.lstrip().startswith("#"))
    provider = (os.environ.get("MEDA_PROVIDER") or values.get("MEDA_PROVIDER", "gemini")).strip().lower()
    key_var = "ANTHROPIC_API_KEY" if provider == "claude" else "GEMINI_API_KEY"
    current = values.get(key_var, "").strip()
    if (env.exists() and current and not current.endswith("...")) or os.environ.get(key_var):
        return
    print("\n  Welcome to Mission MEDA. A few quick questions, one time only.\n")
    if provider == "claude":
        key = getpass.getpass("  1. Paste your Claude API key (it stays hidden as you paste): ").strip()
    else:
        print("  1. Get a free Gemini key: open https://aistudio.google.com/apikey, sign in with Google,")
        print("     tap 'Create API key' and copy it.")
        key = getpass.getpass("     Paste the key here (it stays hidden as you paste): ").strip()
    name = input("  2. What should the crew call you? [Sai]: ").strip() or "Sai"
    while True:
        code = getpass.getpass("  3. Choose a passcode for the app (6+ characters): ").strip()
        if len(code) >= 6:
            break
        print("     That's too short, try again.")
    projects = input(f"  4. Folder with your projects for Lochu [{Path.home() / 'projects'}]: ").strip()
    updates = {key_var: key, "MEDA_OWNER_NAME": name, "MEDA_PASSCODE": code}
    if projects:
        updates["MEDA_PROJECTS_DIR"] = projects
    lines = []
    for line in text.splitlines():
        k = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
        lines.append(f"{k}={updates.pop(k)}" if k in updates else line)
    lines += [f"{k}={v}" for k, v in updates.items()]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n  Saved. You can change these later in the .env file.\n")


first_run_setup()

import uvicorn  # noqa: E402

from meda import config  # noqa: E402


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def make_cert(ip: str) -> tuple[str, str]:
    """Self-signed certificate so phone browsers allow the microphone."""
    cert, key = ROOT / "data" / "cert.pem", ROOT / "data" / "key.pem"
    if cert.exists() and key.exists():
        return str(cert), str(key)
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cert.parent.mkdir(parents=True, exist_ok=True)
    pk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mission MEDA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(pk.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now)
         .not_valid_after(now + datetime.timedelta(days=825))
         .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                     x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
         .sign(pk, hashes.SHA256()))
    key.write_bytes(pk.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                     serialization.NoEncryption()))
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return str(cert), str(key)


def main():
    parser = argparse.ArgumentParser(description="Mission MEDA")
    parser.add_argument("--phone", action="store_true", help="allow your phone on the same Wi-Fi to connect")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.phone:
        if len(config.PASSCODE) < 6:
            sys.exit("Set MEDA_PASSCODE in .env (6+ characters) before opening the app to your phone. "
                     "Lochu can run commands on this computer, so it must be locked.")
        ip = local_ip()
        cert, key = make_cert(ip)
        print(f"\n  Mission MEDA is up.\n  Laptop: https://localhost:{args.port}\n  Phone:  https://{ip}:{args.port}\n"
              "  Your browser will warn about the certificate the first time. That's expected for a\n"
              "  home-made certificate: tap Advanced, then Proceed.\n")
        uvicorn.run("meda.server:app", host="0.0.0.0", port=args.port, ssl_certfile=cert, ssl_keyfile=key)
    else:
        print(f"\n  Mission MEDA is up. Open http://localhost:{args.port} in Chrome or Edge.\n"
              "  Keep this window open while you use it. Close it to switch the crew off.\n")
        threading.Timer(2.0, webbrowser.open, [f"http://localhost:{args.port}"]).start()
        uvicorn.run("meda.server:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
