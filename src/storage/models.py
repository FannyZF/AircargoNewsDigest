from dataclasses import dataclass, field
from datetime import datetime
import uuid
import json


CATEGORY_LABELS = {
    "1": "运价", "2": "运力", "3": "航线", "4": "政策法规",
    "5": "企业动态", "6": "市场报告", "7": "技术与可持续", "8": "其他",
}

REGION_LABELS = {
    "China": "中国", "Asia": "亚洲", "Europe": "欧洲",
    "NorthAmerica": "北美", "SouthAmerica": "南美",
    "MiddleEast": "中东", "Africa": "非洲", "Oceania": "大洋洲", "Global": "全球",
}


@dataclass
class NewsItem:
    url: str
    title: str
    original_text: str
    source: str
    published_at: str = ""
    collected_at: str = field(default_factory=lambda: datetime.now().isoformat())

    translated_title: str = ""
    translated_text: str = ""
    summary: str = ""
    core_extract: str = ""
    keywords: str = "[]"
    categories: str = "[]"
    regions: str = "[]"

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"
    processed_at: str = ""
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "url": self.url, "title": self.title,
            "original_text": self.original_text, "source": self.source,
            "published_at": self.published_at, "collected_at": self.collected_at,
            "translated_title": self.translated_title,
            "translated_text": self.translated_text,
            "summary": self.summary, "keywords": self.keywords,
            "categories": self.categories, "regions": self.regions,
            "status": self.status, "processed_at": self.processed_at,
            "error_message": self.error_message,
        }

    def get_keywords_list(self) -> list:
        try:
            return json.loads(self.keywords)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_categories_list(self) -> list:
        try:
            return json.loads(self.categories)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_regions_list(self) -> list:
        try:
            return json.loads(self.regions)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_category_labels(self) -> list:
        return [CATEGORY_LABELS.get(c, "其他") for c in self.get_categories_list()]

    def get_region_labels(self) -> list:
        return [REGION_LABELS.get(r, r) for r in self.get_regions_list()]
