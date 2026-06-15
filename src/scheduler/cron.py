import signal
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.utils.logger import setup_logger

logger = setup_logger("scheduler")


class Scheduler:
    def __init__(self, config: dict, job_func):
        schedule_cfg = config.get("schedule", {})
        self.enabled = schedule_cfg.get("enabled", True)
        self.time = schedule_cfg.get("time", "08:00")
        self.timezone = schedule_cfg.get("timezone", "Asia/Shanghai")

        hour, minute = self.time.split(":")
        self.scheduler = BackgroundScheduler(timezone=self.timezone)
        self.scheduler.add_job(
            job_func,
            trigger=CronTrigger(hour=int(hour), minute=int(minute)),
            id="daily_digest",
            name="Daily Air Cargo News Digest",
        )
        self._job_func = job_func

    def start_background(self):
        if not self.enabled:
            logger.info("Scheduler is disabled in config")
            return
        self.scheduler.start()
        logger.info("Scheduler started in background, next run at %s daily (timezone: %s)", self.time, self.timezone)

    def start(self):
        if not self.enabled:
            logger.info("Scheduler is disabled in config")
            return

        self.scheduler.start()
        logger.info("Scheduler started, next run at %s daily (timezone: %s)", self.time, self.timezone)

        next_run = self.scheduler.get_job("daily_digest").next_run_time
        if next_run:
            logger.info("Next run: %s", next_run.strftime("%Y-%m-%d %H:%M:%S %Z"))

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

        try:
            while True:
                import time
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            self.stop()

    def stop(self):
        logger.info("Shutting down scheduler...")
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    def run_now(self):
        logger.info("Manual trigger: running job now...")
        self._job_func()
