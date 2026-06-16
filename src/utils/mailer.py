import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
import json

from src.utils.logger import setup_logger

logger = setup_logger("mailer")

SMTP_CONFIG_FILE = Path("data/smtp_config.json")


def load_smtp_config() -> dict:
    if SMTP_CONFIG_FILE.exists():
        try:
            return json.loads(SMTP_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass
    return {}


def save_smtp_config(host: str, port: int, user: str, password: str, sender: str):
    SMTP_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    SMTP_CONFIG_FILE.write_text(json.dumps({
        "host": host, "port": port, "user": user,
        "password": password, "sender": sender,
    }, indent=2), encoding="utf-8")


def send_digest_email(to_emails: list[str], html_path: Path, date_str: str) -> dict:
    cfg = load_smtp_config()
    if not cfg.get("host"):
        return {"sent": 0, "error": "SMTP 未配置"}

    html_content = html_path.read_text(encoding="utf-8") if html_path.exists() else ""

    sent = 0
    failed = 0
    errors = []

    for email in to_emails:
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = cfg["sender"]
            msg["To"] = email
            msg["Subject"] = f"空运新闻速递 | {date_str}"

            part = MIMEText(html_content, "html", "utf-8")
            msg.attach(part)

            with smtplib.SMTP_SSL(cfg["host"], cfg["port"]) as server:
                server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["sender"], [email], msg.as_string())

            sent += 1
            logger.info("Email sent to %s", email)

        except Exception as e:
            failed += 1
            errors.append(f"{email}: {e}")
            logger.error("Failed to send to %s: %s", email, e)

    return {"sent": sent, "failed": failed, "errors": errors}
