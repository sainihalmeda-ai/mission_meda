"""Jyothi's side of the system: the food pipe that every request flows through.

Before any agent thinks, Jyothi checks the daily budget and whether that agent
is cooling down. After it answers, she books the tokens it used and sends it to
cool down if it has been running too hot.
"""

import time

from . import config, memory

AGENT_NAMES = ["sonu", "indu", "lochu", "jyothi", "ramu"]


def cost_of(input_tokens: int, output_tokens: int) -> float:
    return input_tokens / 1_000_000 * config.PRICE_IN + output_tokens / 1_000_000 * config.PRICE_OUT


def gate(agent: str) -> str | None:
    """Return a reason this agent can't run right now, or None if it is good to go."""
    today = memory.usage_today()
    if today["calls"] >= config.DAILY_REQUEST_LIMIT:
        return (f"Jyothi here. The crew has used today's {config.DAILY_REQUEST_LIMIT} free requests, so everyone "
                "is resting until the limit resets tomorrow.")
    spent = today["cost_usd"]
    # Jyothi herself can always answer, so you can ask her what's going on.
    if spent >= config.DAILY_BUDGET_USD and agent != "jyothi":
        return (f"Jyothi here. We've used ${spent:.2f} of today's ${config.DAILY_BUDGET_USD:.2f} budget, "
                "so the crew is resting until midnight. You can raise MEDA_DAILY_BUDGET_USD in .env.")
    cd = memory.get_cooldown(agent)
    if cd:
        mins = max(1, round((cd["until"] - time.time()) / 60))
        return (f"Jyothi here. {agent.title()} is cooling down for about {mins} more minute(s) "
                f"({cd['reason']}). Ask me to wake them early if it's urgent.")
    return None


def book(agent: str, input_tokens: int, output_tokens: int) -> None:
    memory.record_usage(agent, input_tokens, output_tokens, cost_of(input_tokens, output_tokens))
    hour = memory.usage_since(3600, agent)
    if agent != "jyothi" and hour["input_tokens"] + hour["output_tokens"] > config.AGENT_TOKENS_PER_HOUR:
        memory.set_cooldown(agent, time.time() + config.COOLDOWN_MINUTES * 60,
                            "used too many tokens in the last hour")


def machine_stats() -> dict:
    """CPU, memory, disk, battery and temperature of the computer the crew runs on."""
    try:
        import psutil
    except ImportError:
        return {"note": "Install psutil to see machine stats: pip install psutil"}
    stats = {
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage(str(config.DATA_DIR.anchor or "/")).percent,
    }
    battery = getattr(psutil, "sensors_battery", lambda: None)()
    if battery:
        stats["battery_percent"] = round(battery.percent)
        stats["plugged_in"] = battery.power_plugged
    temps_fn = getattr(psutil, "sensors_temperatures", None)
    if temps_fn:
        try:
            temps = temps_fn()
            readings = [t.current for group in temps.values() for t in group if t.current]
            if readings:
                stats["hottest_sensor_c"] = round(max(readings), 1)
        except Exception:
            pass
    return stats


def report() -> dict:
    today = memory.usage_today()
    agents = {}
    for name in AGENT_NAMES:
        cd = memory.get_cooldown(name)
        agents[name] = {
            "today": memory.usage_today(name),
            "last_hour_tokens": sum(memory.usage_since(3600, name)[k] for k in ("input_tokens", "output_tokens")),
            "cooling_down_minutes": round((cd["until"] - time.time()) / 60, 1) if cd else 0,
        }
    return {
        "brain": {"provider": config.PROVIDER, "model": config.MODEL or "default"},
        "budget": {"spent_today_usd": today["cost_usd"], "daily_limit_usd": config.DAILY_BUDGET_USD,
                   "left_usd": round(max(0.0, config.DAILY_BUDGET_USD - today["cost_usd"]), 4)},
        "requests": {"used_today": today["calls"], "daily_limit": config.DAILY_REQUEST_LIMIT},
        "per_agent_hourly_token_limit": config.AGENT_TOKENS_PER_HOUR,
        "agents": agents,
        "machine": machine_stats(),
    }
