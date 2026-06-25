import httpx
from pathlib import Path

from src.utils.logger import setup_logger
from src.utils.webhook_store import load_webhook_secret

logger = setup_logger("webhook")


def send_to_webhooks(webhooks: list[dict], html_path: Path, date_str: str) -> dict:
    sent = 0
    failed = 0
    errors = []

    html_content = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
    if not html_content:
        return {"sent": 0, "failed": 0, "error": "日报文件不存在"}

    payload = {
        "date": date_str,
        "title": f"空运新闻速递 | {date_str}",
        "html": html_content,
    }

    secret = load_webhook_secret(webhooks)
    base_headers = {"Content-Type": "application/json", "User-Agent": "AirCargoNewsDigest/1.0"}
    if secret:
        base_headers["X-Webhook-Secret"] = secret

    for wh in webhooks:
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(wh["url"], json=payload, headers=base_headers)
                if resp.status_code < 400:
                    sent += 1
                    logger.info("Webhook sent to %s: %d", wh["url"], resp.status_code)
                else:
                    failed += 1
                    errors.append(f"{wh['url']}: HTTP {resp.status_code}")
                    logger.warning("Webhook failed %s: %d %s", wh["url"], resp.status_code, resp.text[:200])
        except Exception as e:
            failed += 1
            errors.append(f"{wh['url']}: {e}")
            logger.error("Webhook error %s: %s", wh["url"], e)

    return {"sent": sent, "failed": failed, "errors": errors}
