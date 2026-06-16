from datetime import datetime, timedelta
from pathlib import Path
from collections import OrderedDict

from jinja2 import Environment, FileSystemLoader

from src.storage.db import Database
from src.storage.models import CATEGORY_LABELS, REGION_LABELS
from src.utils.logger import setup_logger

logger = setup_logger("reporter")


class DigestReporter:
    def __init__(self, config: dict, db: Database):
        self.config = config
        self.db = db
        output_dir = config.get("output", {}).get("dir", "./output")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        template_dir = Path(__file__).parent / "templates"
        self.jinja = Environment(loader=FileSystemLoader(str(template_dir)))
        self.jinja.globals["CATEGORY_LABELS"] = CATEGORY_LABELS
        self.jinja.globals["REGION_LABELS"] = REGION_LABELS
        self.template = self.jinja.get_template("daily.html.j2")

    def generate(self, date_str: str = None, collection_date: str = None) -> str | None:
        # date_str = display date (news date, usually yesterday)
        # collection_date = actual collected_at date to query (usually today)
        now = datetime.now()
        if date_str is None:
            date_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        if collection_date is None:
            collection_date = now.strftime("%Y-%m-%d")

        items = self.db.get_processed_by_date(collection_date)
        if not items:
            logger.warning("No processed items found for %s", collection_date)
            return None

        source_order = OrderedDict()
        for item in items:
            if item.source not in source_order:
                source_order[item.source] = []
            source_order[item.source].append(item)

        sources = ", ".join(source_order.keys())
        date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y年%m月%d日")

        html = self.template.render(
            date_str=date_str, date_display=date_display,
            total_count=len(items), source_groups=list(source_order.items()),
            sources=sources,
        )

        filename_pattern = self.config.get("output", {}).get("filename_pattern", "daily_{date}.html")
        filename = filename_pattern.format(date=date_str)
        output_path = self.output_dir / filename
        output_path.write_text(html, encoding="utf-8")
        logger.info("Digest written to %s", output_path)
        return str(output_path)
