import json
import secrets
from pathlib import Path

WEBHOOK_FILE = Path("data/webhooks.json")


def load_webhooks() -> list[dict]:
    if WEBHOOK_FILE.exists():
        try:
            data = json.loads(WEBHOOK_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, KeyError):
            pass
    return []


def save_webhooks(webhooks: list[dict]):
    WEBHOOK_FILE.parent.mkdir(parents=True, exist_ok=True)
    WEBHOOK_FILE.write_text(json.dumps(webhooks, indent=2, ensure_ascii=False), encoding="utf-8")


def add_webhook(url: str, name: str = "") -> dict | None:
    webhooks = load_webhooks()
    url = url.strip()
    for w in webhooks:
        if w["url"] == url:
            return None
    entry = {
        "url": url,
        "name": name or url,
        "enabled": True,
        "secret": secrets.token_hex(16),
    }
    webhooks.append(entry)
    save_webhooks(webhooks)
    return entry


def remove_webhook(url: str) -> bool:
    webhooks = load_webhooks()
    before = len(webhooks)
    webhooks = [w for w in webhooks if w["url"] != url]
    if len(webhooks) < before:
        save_webhooks(webhooks)
        return True
    return False


def regenerate_secret(url: str) -> str | None:
    webhooks = load_webhooks()
    for w in webhooks:
        if w["url"] == url:
            w["secret"] = secrets.token_hex(16)
            save_webhooks(webhooks)
            return w["secret"]
    return None


def get_active_webhooks() -> list[dict]:
    return [w for w in load_webhooks() if w.get("enabled", True)]
