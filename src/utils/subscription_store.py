import json
from pathlib import Path


SUB_FILE = Path("data/subscribers.json")


def load_subscribers() -> list[dict]:
    if SUB_FILE.exists():
        try:
            data = json.loads(SUB_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, KeyError):
            pass
    return []


def save_subscribers(subscribers: list[dict]):
    SUB_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUB_FILE.write_text(json.dumps(subscribers, indent=2, ensure_ascii=False), encoding="utf-8")


def add_subscriber(email: str) -> bool:
    subs = load_subscribers()
    email = email.strip().lower()
    for s in subs:
        if s["email"] == email:
            return False
    subs.append({"email": email, "active": True})
    save_subscribers(subs)
    return True


def remove_subscriber(email: str) -> bool:
    subs = load_subscribers()
    email = email.strip().lower()
    before = len(subs)
    subs = [s for s in subs if s["email"] != email]
    if len(subs) < before:
        save_subscribers(subs)
        return True
    return False


def get_active_subscribers() -> list[str]:
    return [s["email"] for s in load_subscribers() if s.get("active", True)]
