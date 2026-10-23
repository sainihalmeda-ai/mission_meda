"""Web server for the Mission MEDA app."""

import hmac
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import agents, config, health, memory, procs
from .brain import Crew

WEB = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Mission MEDA")
crew: Crew | None = None


def get_crew() -> Crew:
    global crew
    if crew is None:
        crew = Crew()
    return crew


@app.middleware("http")
async def passcode_guard(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/login" and config.PASSCODE:
        given = request.headers.get("x-meda-passcode", "")
        if not hmac.compare_digest(given, config.PASSCODE):
            return JSONResponse({"detail": "Passcode needed"}, status_code=401)
    return await call_next(request)


class Login(BaseModel):
    passcode: str = ""


class Chat(BaseModel):
    text: str
    agent: str | None = None


class Decision(BaseModel):
    approval_id: str
    decisions: dict[str, bool]


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.post("/api/login")
def login(body: Login):
    ok = not config.PASSCODE or hmac.compare_digest(body.passcode, config.PASSCODE)
    return {"ok": ok, "needs_passcode": bool(config.PASSCODE)}


@app.get("/api/crew")
def crew_info():
    return {"owner": config.OWNER_NAME, "crew": agents.public_info(), "pending": get_crew().all_pending()}


@app.post("/api/chat")
def chat(body: Chat):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Say something first")
    return get_crew().handle(text[:8000], body.agent)


@app.post("/api/decide")
def decide(body: Decision):
    return get_crew().decide(body.approval_id, body.decisions)


@app.get("/api/health")
def health_report():
    rep = health.report()
    rep["background_processes"] = procs.listing()
    return rep


@app.get("/api/board")
def board():
    """Today's tasks, applications and recent moods for the side panel."""
    return {"tasks": memory.list_tasks(), "applications": memory.list_applications()[:10],
            "moods": memory.mood_history(7), "facts": memory.recall("", 10)}


@app.post("/api/reset/{agent}")
def reset(agent: str):
    if agent not in agents.CREW:
        raise HTTPException(404, "No such agent")
    get_crew().reset(agent)
    return {"ok": True}


@app.on_event("shutdown")
def shutdown():
    procs.stop_all()
