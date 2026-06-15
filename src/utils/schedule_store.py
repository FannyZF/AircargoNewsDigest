import json
from pathlib import Path


SCHEDULE_FILE = Path("data/schedule.json")


def load_schedule() -> dict:
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass
    return {"time": "23:00", "timezone": "Asia/Shanghai"}


def save_schedule(time: str, timezone: str = "Asia/Shanghai"):
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(json.dumps({"time": time, "timezone": timezone}, indent=2), encoding="utf-8")


def get_schedule_config(config: dict) -> dict:
    saved = load_schedule()
    cfg = config.get("schedule", {})
    return {
        "time": saved.get("time") or cfg.get("time", "23:00"),
        "timezone": saved.get("timezone") or cfg.get("timezone", "Asia/Shanghai"),
        "enabled": cfg.get("enabled", True),
    }
