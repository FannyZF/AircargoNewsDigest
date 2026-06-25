import sys
import os
import argparse
from datetime import datetime
from pathlib import Path

import yaml

from src.utils.logger import setup_logger
from src.storage.db import Database
from src.storage.models import NewsItem
from src.collector.scraper import Scraper
from src.processor.pipeline import ProcessingPipeline
from src.reporter.digest import DigestReporter
from src.scheduler.cron import Scheduler

logger = setup_logger("main")


def load_config(config_path: str = "config.yaml") -> dict:
    path = Path(config_path)
    if not path.exists():
        logger.error("Config file not found: %s", path)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_init(_config: dict, _args):
    if Path("config.yaml").exists():
        logger.warning("config.yaml already exists, skipping init")
        return
    default_config = """# ==================== 新闻源配置 ====================
sources:
  - name: "Air Cargo News"
    base_url: "https://www.aircargonews.net"
    list_url: "https://www.aircargonews.net/"
    enabled: true
    selectors:
      list_container: "article.summary"
      title: "span.post-title"
      link: "a"
      date: "time.pubdate"
      date_attr: "datetime"
      summary: "p.excerpt"
    article_selector:
      content: "div.entry-content"

  - name: "Airfreight News"
    base_url: "https://airfreight.news"
    list_url: "https://airfreight.news/"
    enabled: true
    selectors:
      list_container: "div.media.mb-3.clickbox"
      title: ".media-title a"
      link: ".media-title a"
      date: ".small"
      date_attr: "text"
      date_regex: "\\\\|\\\\s*(.+)$"
      summary: ""
    article_selector:
      content: "div.article-content, article, div.content"

# ==================== LLM 配置 ====================
llm:
  provider: "deepseek"
  model: "deepseek-v4-flash"
  api_key: "${DEEPSEEK_API_KEY}"
  base_url: "https://api.deepseek.com"
  temperature: 0.3
  max_tokens: 4096
  batch_size: 5

# ==================== 调度配置 ====================
schedule:
  enabled: true
  time: "08:00"
  timezone: "Asia/Shanghai"

# ==================== 输出配置 ====================
output:
  dir: "./output"
  filename_pattern: "daily_{date}.html"
  keep_days: 30

# ==================== 抓取配置 ====================
scraping:
  request_interval: 2
  user_agents:
    - "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    - "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0"
  timeout: 30
  max_retries: 3
  lookback_days: 1
"""
    Path("config.yaml").write_text(default_config, encoding="utf-8")
    logger.info("Generated default config.yaml")


def cmd_collect(config: dict, _args):
    db = Database()
    scraper = Scraper(config)
    lookback = config.get("scraping", {}).get("lookback_days", 1)

    total_collected = 0
    total_skipped = 0

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue

        logger.info("--- Collecting from: %s ---", source["name"])

        try:
            items = scraper.scrape_list(source, lookback_days=lookback)
            if not items:
                logger.info("No items found within %d days from %s", lookback, source["name"])
                continue

            content_sel = source.get("article_selector", {}).get("content", "")

            for item in items:
                if db.url_exists(item["url"]):
                    total_skipped += 1
                    continue

                body = ""
                if content_sel:
                    body = scraper.scrape_article(item["url"], content_sel)

                news_item = NewsItem(
                    url=item["url"],
                    title=item["title"],
                    original_text=body or item.get("summary", ""),
                    source=item["source"],
                    published_at=item.get("published_at", ""),
                )
                db.insert_news(news_item)
                total_collected += 1
                logger.debug("Inserted: %s", item["title"][:60])

        except Exception as e:
            logger.error("Failed to collect from %s: %s", source["name"], e)

    logger.info("Collection complete: %d new, %d skipped (duplicates)", total_collected, total_skipped)


def cmd_backfill(config: dict, _args):
    db = Database()
    scraper = Scraper(config)
    since_date = "2026-05-01"
    max_pages = 50

    total_collected = 0
    total_skipped = 0

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue

        pagination = source.get("pagination", {})
        if not pagination.get("pattern"):
            logger.info("Skipping %s: no pagination configured", source["name"])
            continue

        logger.info("--- Backfilling from: %s (since %s) ---", source["name"], since_date)

        try:
            items = scraper.scrape_pages(source, since_date=since_date, max_pages=max_pages)
            if not items:
                logger.info("No items found for %s", source["name"])
                continue

            content_sel = source.get("article_selector", {}).get("content", "")

            for item in items:
                if db.url_exists(item["url"]):
                    total_skipped += 1
                    continue

                body = ""
                if content_sel:
                    body = scraper.scrape_article(item["url"], content_sel)

                news_item = NewsItem(
                    url=item["url"],
                    title=item["title"],
                    original_text=body or item.get("summary", ""),
                    source=item["source"],
                    published_at=item.get("published_at", ""),
                )
                db.insert_news(news_item)
                total_collected += 1

        except Exception as e:
            logger.error("Failed to backfill from %s: %s", source["name"], e)

    logger.info("Backfill complete: %d new, %d skipped (duplicates)", total_collected, total_skipped)


def cmd_process(config: dict, _args):
    db = Database()
    pipeline = ProcessingPipeline(config, db)
    stats = pipeline.process_pending()
    logger.info("Processing complete: %s", stats)


def cmd_report(config: dict, args):
    db = Database()
    reporter = DigestReporter(config, db)
    date_str = getattr(args, 'date', None) if args else None
    path = reporter.generate(date_str)
    if path:
        logger.info("Report generated: %s", path)
    else:
        logger.warning("No report generated for %s", date_str or "today")


def cmd_run(config: dict, args):
    cmd_collect(config, args)
    cmd_process(config, args)
    cmd_report(config, args)

    db = Database()
    stats = db.get_stats()
    logger.info("=== Run complete ===")
    logger.info("DB stats: total=%d, pending=%d, processed=%d, failed=%d",
                 stats["total"], stats["pending"], stats["processed"], stats["failed"])


def cmd_schedule(config: dict, _args):
    def daily_job():
        logger.info("=== Scheduled daily run starting ===")
        try:
            cmd_collect(config, None)
            cmd_process(config, None)
            cmd_report(config, None)
            logger.info("=== Scheduled daily run complete ===")
        except Exception as e:
            logger.error("Scheduled run failed: %s", e)

    scheduler = Scheduler(config, daily_job)
    scheduler.start()


def cmd_web(config: dict, _args):
    import uvicorn
    import os
    import threading
    from src.web.app import create_app, create_public_app

    port = int(os.environ.get("PORT", "18903"))
    admin_port = int(os.environ.get("ADMIN_PORT", "18913"))

    # Public app (subscribe only) on PORT
    public_app = create_public_app(config)
    def run_public():
        uvicorn.run(public_app, host="0.0.0.0", port=port, log_level="info")

    # Admin app (full) on ADMIN_PORT
    admin_app = create_app(config)
    def run_admin():
        uvicorn.run(admin_app, host="0.0.0.0", port=admin_port, log_level="info")

    # Start daily scheduler
    from src.scheduler.cron import Scheduler
    def daily_job():
        logger.info("=== Scheduled daily run starting ===")
        try:
            cmd_collect(config, None)
            cmd_process(config, None)
            cmd_report(config, None)
            from src.utils.subscription_store import get_active_subscribers
            from src.utils.mailer import send_digest_email
            from pathlib import Path
            from datetime import datetime, timedelta
            subs = get_active_subscribers()
            if subs:
                yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
                pattern = config.get("output", {}).get("filename_pattern", "daily_{date}.html")
                html_file = Path(config.get("output", {}).get("dir", "./output")) / pattern.format(date=yesterday)
                if html_file.exists():
                    result = send_digest_email(subs, html_file, yesterday)
                    logger.info("Email send result: %s", result)
                from src.utils.webhook_store import get_active_webhooks
                from src.utils.webhook_sender import send_to_webhooks
                webhooks = get_active_webhooks()
                if webhooks and html_file.exists():
                    wh_result = send_to_webhooks(webhooks, html_file, yesterday)
                    logger.info("Webhook send result: %s", wh_result)
            logger.info("=== Scheduled daily run complete ===")
        except Exception as e:
            logger.error("Scheduled run failed: %s", e)

    scheduler = Scheduler(config, daily_job)
    scheduler.start_background()
    from src.utils.schedule_store import get_schedule_config
    sched_cfg = get_schedule_config(config)
    logger.info("Daily scheduler started, runs at %s %s", sched_cfg["time"], sched_cfg["timezone"])

    logger.info("Public: http://0.0.0.0:%d (subscribe only)", port)
    logger.info("Admin: http://0.0.0.0:%d (full management)", admin_port)

    t1 = threading.Thread(target=run_public, daemon=True)
    t1.start()
    run_admin()


def main():
    parser = argparse.ArgumentParser(description="AirCargoNews Digest - 空运新闻日报聚合工具")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "collect", "process", "report", "schedule", "init", "web", "backfill"],
                        help="Command to execute")
    parser.add_argument("--date", "-d", help="Target date (YYYY-MM-DD) for report command")
    parser.add_argument("--config", "-c", default="config.yaml", help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)

    commands = {
        "init": cmd_init,
        "collect": cmd_collect,
        "process": cmd_process,
        "report": cmd_report,
        "run": cmd_run,
        "schedule": cmd_schedule,
        "web": cmd_web,
        "backfill": cmd_backfill,
    }

    commands[args.command](config, args)


if __name__ == "__main__":
    main()
