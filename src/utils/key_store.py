import json
import os
from pathlib import Path


KEY_FILE = Path("data/api_key.json")


def load_api_key() -> str:
    if KEY_FILE.exists():
        try:
            data = json.loads(KEY_FILE.read_text(encoding="utf-8"))
            return data.get("api_key", "")
        except (json.JSONDecodeError, KeyError):
            return ""
    return ""


def save_api_key(key: str):
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(json.dumps({"api_key": key}, indent=2), encoding="utf-8")


def get_api_key(config: dict) -> str:
    saved = load_api_key()
    if saved:
        return saved

    llm_cfg = config.get("llm", {})
    key = llm_cfg.get("api_key", "")
    if key.startswith("${") and key.endswith("}"):
        env_var = key[2:-1]
        return os.environ.get(env_var, "")
    return key
