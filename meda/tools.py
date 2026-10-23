"""The tools each crew member can use, and the code that runs them."""

import json
from datetime import datetime

from . import config, health, lockbox, memory, procs


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": properties, "required": required or []},
    }


S = {"type": "string"}
I = {"type": "integer"}

# ---------- tool definitions ----------

SHARED = [
    _tool("remember_fact", "Save something worth remembering about Sai for the whole crew: goals, preferences, "
          "people, exam dates, health notes, project details. Use whenever Sai shares something lasting.",
          {"text": S, "topic": {"type": "string", "description": "e.g. academics, career, health, projects, family"}},
          ["text"]),
    _tool("recall_facts", "Search what the crew remembers about Sai. Leave query empty for the latest facts.",
          {"query": S}),
    _tool("forget_fact", "Delete a remembered fact by its id when Sai asks you to forget it or it is outdated.",
          {"id": I}, ["id"]),
]

SCHEDULE = [
    _tool("add_task", "Add a task, class, exam, assignment, deadline or study block to Sai's schedule.",
          {"title": S,
           "kind": {"type": "string", "enum": ["task", "class", "exam", "assignment", "deadline", "study", "earning", "chore"]},
           "due": {"type": "string", "description": "Date or date-time, e.g. 2026-11-02 or 2026-11-02 14:00"}},
          ["title"]),
    _tool("list_tasks", "List Sai's open tasks and schedule, soonest first.", {"include_done": {"type": "boolean"}}),
    _tool("complete_task", "Mark a task as done by id.", {"id": I}, ["id"]),
]

JOBS = [
    _tool("save_job_application", "Add or update a job or internship application. Pass id to update an existing one.",
          {"company": S, "role": S,
           "status": {"type": "string", "enum": ["planned", "applied", "oa", "interview", "offer", "rejected", "withdrawn"]},
           "link": S, "notes": S, "id": I},
          ["company"]),
    _tool("list_job_applications", "Show every job and internship application with its status.", {}),
]

MOOD = [
    _tool("log_mood", "Record how Sai is feeling, with an optional 1-10 score and a short note.",
          {"mood": S, "score": I, "note": S}, ["mood"]),
    _tool("mood_history", "See Sai's recent mood check-ins to notice patterns.", {"limit": I}),
]

LOCHU = [
    _tool("list_projects", "List the project folders inside Sai's projects directory.", {}),
    _tool("read_file", "Read a text file inside the projects directory (path relative to it). "
          ".env and vault files are off limits.", {"path": S}, ["path"]),
    _tool("list_files", "List files in a folder inside the projects directory.", {"path": S}),
    _tool("list_credentials", "List the NAMES of credentials stored in Sai's vault. You never see the values. "
          "Use them in commands as $NAME and they are filled in when the command runs.", {}),
    _tool("run_command", "Run a shell command inside a project folder (build, test, debug, deploy, simulate). "
          "Sai must approve every command in the app before it runs. Explain in one line why you need it.",
          {"command": S, "folder": {"type": "string", "description": "Folder relative to the projects directory"},
           "why": S, "timeout_seconds": I},
          ["command", "why"]),
    _tool("start_process", "Launch a long-running process in the background (dev server, bot, simulation). "
          "Needs Sai's approval.", {"name": S, "command": S, "folder": S, "why": S}, ["name", "command", "why"]),
    _tool("stop_process", "Terminate a background process by name. Needs Sai's approval.",
          {"name": S, "why": S}, ["name"]),
    _tool("relaunch_process", "Stop and restart a background process with the same command. Needs Sai's approval.",
          {"name": S, "why": S}, ["name"]),
    _tool("process_logs", "Read the latest output of a background process.", {"name": S, "lines": I}, ["name"]),
    _tool("list_processes", "List background processes Lochu has started and whether they are running.", {}),
]

JYOTHI = [
    _tool("system_health", "Full health report: today's spend vs budget, each agent's token use and cooldowns, "
          "the computer's CPU, memory, disk, battery and temperature, and Lochu's background processes.", {}),
    _tool("cool_down_agent", "Pause an agent for some minutes so it rests and stops using budget.",
          {"agent": {"type": "string", "enum": health.AGENT_NAMES}, "minutes": I, "reason": S}, ["agent", "minutes"]),
    _tool("wake_agent", "End an agent's cooldown early.",
          {"agent": {"type": "string", "enum": health.AGENT_NAMES}}, ["agent"]),
    _tool("refresh_agent", "Start a fresh conversation room for an agent when its history is long or confused. "
          "Shared memory is kept.", {"agent": {"type": "string", "enum": health.AGENT_NAMES}}, ["agent"]),
]

# Tools that wait for Sai's tap before they run.
NEEDS_APPROVAL = {"run_command", "start_process", "stop_process", "relaunch_process"}


def describe_action(name: str, args: dict) -> str:
    """Plain-language summary shown on the approval card."""
    if name == "run_command":
        return f"Run in {args.get('folder') or 'projects folder'}:\n{args.get('command')}"
    if name == "start_process":
        return f"Start '{args.get('name')}' in {args.get('folder') or 'projects folder'}:\n{args.get('command')}"
    if name == "stop_process":
        return f"Stop the background process '{args.get('name')}'"
    if name == "relaunch_process":
        return f"Restart the background process '{args.get('name')}'"
    return f"{name} {json.dumps(args)}"


def blocked_reason(name: str, args: dict) -> str | None:
    """Lockbox check that happens before an action is even offered for approval."""
    if name in ("run_command", "start_process"):
        reason = lockbox.check_command(args.get("command", ""))
        if reason:
            return reason
        try:
            lockbox.safe_path(args.get("folder", ""))
        except PermissionError as e:
            return str(e)
    return None


# ---------- running tools ----------

def _forbidden_file(path: str) -> bool:
    lower = path.lower().replace("\\", "/").split("/")[-1]
    return lower.startswith(".env") or lower.endswith(".env") or "vault" in lower or lower.endswith((".pem", ".key"))


def execute(name: str, args: dict, agent: str) -> str:
    """Run one tool and return text for the agent. Errors come back as text too."""
    try:
        result = _execute(name, args, agent)
    except PermissionError as e:
        return f"ERROR: {e}"
    except Exception as e:  # keep the conversation alive whatever goes wrong
        return f"ERROR: {type(e).__name__}: {e}"
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)


def _execute(name: str, a: dict, agent: str):
    if name == "remember_fact":
        return f"Saved as fact #{memory.remember(a['text'], a.get('topic', 'general'), agent)}."
    if name == "recall_facts":
        return memory.recall(a.get("query", "")) or "Nothing remembered yet."
    if name == "forget_fact":
        return "Forgotten." if memory.forget(int(a["id"])) else "No fact with that id."

    if name == "add_task":
        return f"Added task #{memory.add_task(a['title'], a.get('kind', 'task'), a.get('due', ''))}."
    if name == "list_tasks":
        return memory.list_tasks(bool(a.get("include_done"))) or "No open tasks."
    if name == "complete_task":
        return "Marked done." if memory.complete_task(int(a["id"])) else "No task with that id."

    if name == "save_job_application":
        app_id = memory.save_application(a["company"], a.get("role", ""), a.get("status", "planned"),
                                         a.get("link", ""), a.get("notes", ""), a.get("id"))
        return f"Saved application #{app_id}."
    if name == "list_job_applications":
        return memory.list_applications() or "No applications tracked yet."

    if name == "log_mood":
        return f"Logged mood #{memory.log_mood(a['mood'], a.get('score'), a.get('note', ''))}."
    if name == "mood_history":
        return memory.mood_history(int(a.get("limit", 14))) or "No mood check-ins yet."

    if name == "list_projects":
        base = config.PROJECTS_DIR
        if not base.exists():
            return f"The projects folder {base} doesn't exist yet. Set MEDA_PROJECTS_DIR in .env."
        return sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    if name == "list_files":
        folder = lockbox.safe_path(a.get("path", ""))
        return sorted((p.name + ("/" if p.is_dir() else "")) for p in folder.iterdir())[:300]
    if name == "read_file":
        if _forbidden_file(a["path"]):
            return "ERROR: Lockbox: secret files (.env, vault, keys) are never shown to agents."
        path = lockbox.safe_path(a["path"])
        text = path.read_text(encoding="utf-8", errors="replace")
        return procs._trim(text) if len(text) < 60000 else procs._trim(text[:60000]) + "\n[file truncated]"
    if name == "list_credentials":
        names = lockbox.credential_names()
        return names or f"The vault is empty. Sai can add NAME=value lines to {config.VAULT_PATH}."
    if name == "run_command":
        return procs.run(a["command"], a.get("folder", ""), int(a.get("timeout_seconds", 120)))
    if name == "start_process":
        return procs.start(a["name"], a["command"], a.get("folder", ""))
    if name == "stop_process":
        return procs.stop(a["name"])
    if name == "relaunch_process":
        return procs.relaunch(a["name"])
    if name == "process_logs":
        return procs.logs(a["name"], int(a.get("lines", 80)))
    if name == "list_processes":
        return procs.listing() or "No background processes."

    if name == "system_health":
        rep = health.report()
        rep["background_processes"] = procs.listing()
        rep["checked_at"] = datetime.now().isoformat(timespec="seconds")
        return rep
    if name == "cool_down_agent":
        import time
        mins = max(1, int(a["minutes"]))
        memory.set_cooldown(a["agent"], time.time() + mins * 60, a.get("reason", "Jyothi's call"))
        return f"{a['agent'].title()} is cooling down for {mins} minutes."
    if name == "wake_agent":
        memory.clear_cooldown(a["agent"])
        return f"{a['agent'].title()} is awake."
    if name == "refresh_agent":
        memory.clear_room(f"{a['agent']}@{config.PROVIDER}")
        return f"{a['agent'].title()} has a fresh conversation room. Shared memory is kept."

    return f"ERROR: unknown tool {name}"
