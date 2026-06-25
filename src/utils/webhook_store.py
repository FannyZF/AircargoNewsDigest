import json
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


def add_webhook(url: str, name: str = "") -> bool:
    webhooks = load_webhooks()
    url = url.strip()
    for w in webhooks:
        if w["url"] == url:
            return False
    webhooks.append({"url": url, "name": name or url, "enabled": True})
    save_webhooks(webhooks)
    return True


def remove_webhook(url: str) -> bool:
    webhooks = load_webhooks()
    before = len(webhooks)
    webhooks = [w for w in webhooks if w["url"] != url]
    if len(webhooks) < before:
        save_webhooks(webhooks)
        return True
    return False


def get_active_webhooks() -> list[dict]:
    return [w for w in load_webhooks() if w.get("enabled", True)]


SECRET_FILE = Path("data/webhook_secret.json")


def load_webhook_secret(webhooks: list[dict]) -> str:
    # per-webhook: use each webhook's own secret, fallback to global
    if SECRET_FILE.exists():
        try:
            data = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
            return data.get("secret", "")
        except (json.JSONDecodeError, KeyError):
            pass
    return ""


def save_webhook_secret(secret: str):
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRET_FILE.write_text(json.dumps({"secret": secret}, indent=2), encoding="utf-8")
