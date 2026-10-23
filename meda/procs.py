"""Lochu's workbench: runs commands and keeps track of background processes.

Nothing in here is called until you approve the command in the app.
"""

import os
import subprocess
import threading
import time
from collections import deque

from . import lockbox

MAX_OUTPUT = 8000  # characters of output handed back to the agent


def _env_with_vault() -> dict:
    """Your normal environment plus the vault's credentials, for the subprocess only."""
    env = dict(os.environ)
    env.update(lockbox.load_vault())
    return env


def _trim(text: str) -> str:
    text = lockbox.scrub(text)
    if len(text) > MAX_OUTPUT:
        half = MAX_OUTPUT // 2
        text = text[:half] + f"\n... [{len(text) - MAX_OUTPUT} characters cut] ...\n" + text[-half:]
    return text


def run(command: str, cwd: str = "", timeout: int = 120) -> str:
    """Run a command to completion and return its exit code and output."""
    workdir = lockbox.safe_path(cwd)
    try:
        done = subprocess.run(command, shell=True, cwd=workdir, env=_env_with_vault(),
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "") if isinstance(e.stdout, str) else ""
        return _trim(f"Timed out after {timeout}s. Partial output:\n{out}")
    output = (done.stdout or "") + (("\n[stderr]\n" + done.stderr) if done.stderr else "")
    return _trim(f"exit code {done.returncode}\n{output}")


class Background:
    def __init__(self, name: str, command: str, cwd: str):
        self.name, self.command, self.cwd = name, command, cwd
        self.started = time.time()
        self.lines: deque[str] = deque(maxlen=400)
        self.proc = subprocess.Popen(command, shell=True, cwd=lockbox.safe_path(cwd), env=_env_with_vault(),
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     start_new_session=(os.name != "nt"))
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.append(line.rstrip("\n"))

    def status(self) -> dict:
        code = self.proc.poll()
        return {"name": self.name, "command": self.command, "folder": self.cwd or ".",
                "running": code is None, "exit_code": code,
                "uptime_min": round((time.time() - self.started) / 60, 1)}

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


_bg: dict[str, Background] = {}


def start(name: str, command: str, cwd: str = "") -> str:
    if name in _bg and _bg[name].proc.poll() is None:
        return f"'{name}' is already running. Stop or relaunch it instead."
    _bg[name] = Background(name, command, cwd)
    time.sleep(1.5)
    return _trim(f"Started '{name}'. First output:\n" + "\n".join(_bg[name].lines))


def stop(name: str) -> str:
    if name not in _bg:
        return f"No process called '{name}'."
    _bg[name].stop()
    return f"Stopped '{name}'."


def relaunch(name: str) -> str:
    if name not in _bg:
        return f"No process called '{name}'."
    old = _bg.pop(name)
    old.stop()
    return start(name, old.command, old.cwd)


def logs(name: str, lines: int = 80) -> str:
    if name not in _bg:
        return f"No process called '{name}'."
    return _trim("\n".join(list(_bg[name].lines)[-lines:]) or "(no output yet)")


def listing() -> list[dict]:
    return [p.status() for p in _bg.values()]


def stop_all() -> None:
    for p in _bg.values():
        p.stop()
