from dataclasses import dataclass, field
from datetime import datetime
import uuid
import json


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
    keywords: str = "[]"
    category: str = ""
    china_relevance: str = ""
    china_angle: str = ""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"
    processed_at: str = ""
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "original_text": self.original_text,
            "source": self.source,
            "published_at": self.published_at,
            "collected_at": self.collected_at,
            "translated_title": self.translated_title,
            "translated_text": self.translated_text,
            "summary": self.summary,
            "keywords": self.keywords,
            "category": self.category,
            "china_relevance": self.china_relevance,
            "china_angle": self.china_angle,
            "status": self.status,
            "processed_at": self.processed_at,
            "error_message": self.error_message,
        }

    def get_keywords_list(self) -> list:
        try:
            return json.loads(self.keywords)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_category_label(self) -> str:
        mapping = {
            "1": "运价", "2": "运力", "3": "航线",
            "4": "政策法规", "5": "企业动态", "6": "市场报告",
            "7": "技术与可持续", "8": "其他"
        }
        return mapping.get(self.category, "其他")

    def get_china_badge(self) -> str:
        mapping = {"high": "★ 中国相关", "medium": "☆ 亚太相关", "low": "", "none": ""}
        return mapping.get(self.china_relevance, "")
