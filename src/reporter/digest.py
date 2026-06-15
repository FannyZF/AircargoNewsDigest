import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.storage.db import Database
from src.utils.logger import setup_logger

logger = setup_logger("reporter")

CATEGORY_ORDER = [
    ("1", "运价"),
    ("2", "运力"),
    ("3", "航线"),
    ("4", "政策法规"),
    ("5", "企业动态"),
    ("6", "市场报告"),
    ("7", "技术与可持续"),
    ("8", "其他"),
]


class DigestReporter:
    def __init__(self, config: dict, db: Database):
        self.config = config
        self.db = db
        output_dir = config.get("output", {}).get("dir", "./output")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        template_dir = Path(__file__).parent / "templates"
        self.jinja = Environment(loader=FileSystemLoader(str(template_dir)))
        self.template = self.jinja.get_template("daily.html.j2")

    def generate(self, date_str: str = None) -> str | None:
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        items = self.db.get_processed_by_date(date_str)
        if not items:
            logger.warning("No processed items found for %s", date_str)
            return None

        headlines, rest = self._select_headlines(items)

        categories = []
        for cat_id, cat_name in CATEGORY_ORDER:
            cat_items = [i for i in rest if i.category == cat_id]
            cat_items.sort(key=lambda x: (0 if x.china_relevance == "high" else 1 if x.china_relevance == "medium" else 2))
            categories.append((cat_id, cat_name, cat_items))

        all_kw_counter = Counter()
        for item in items:
            for kw in item.get_keywords_list():
                all_kw_counter[kw] += 1

        total = sum(all_kw_counter.values()) or 1
        all_keywords = []
        for kw, count in all_kw_counter.most_common(40):
            size = max(12, min(24, 12 + int(12 * count / total * 20)))
            all_keywords.append((kw, size))

        china_count = sum(1 for i in items if i.china_relevance in ("high", "medium"))
        china_high = sum(1 for i in items if i.china_relevance == "high")
        china_medium = sum(1 for i in items if i.china_relevance == "medium")

        sources = ", ".join(sorted(set(i.source for i in items)))

        date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y年%m月%d日")

        html = self.template.render(
            date_str=date_str,
            date_display=date_display,
            total_count=len(items),
            headlines=headlines,
            categories=categories,
            all_keywords=all_keywords,
            china_count=china_count,
            china_high_count=china_high,
            china_medium_count=china_medium,
            sources=sources,
        )

        filename_pattern = self.config.get("output", {}).get("filename_pattern", "daily_{date}.html")
        filename = filename_pattern.format(date=date_str)
        output_path = self.output_dir / filename
        output_path.write_text(html, encoding="utf-8")
        logger.info("Digest written to %s", output_path)
        return str(output_path)

    @staticmethod
    def _select_headlines(items: list) -> tuple[list, list]:
        china_high = [i for i in items if i.china_relevance == "high"]
        remaining = [i for i in items if i.china_relevance != "high"]

        headlines = china_high[:5]
        if len(headlines) < 3:
            for item in remaining[: (5 - len(headlines))]:
                headlines.append(item)

        rest = [i for i in items if i not in headlines]
        return headlines, rest
