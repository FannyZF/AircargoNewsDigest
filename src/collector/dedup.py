import re
from urllib.parse import urlparse

from src.utils.logger import setup_logger

logger = setup_logger("dedup")


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    normalized = normalized.rstrip("/")
    return normalized


def title_similarity(a: str, b: str) -> float:
    a_set = set(re.findall(r"\w+", a.lower()))
    b_set = set(re.findall(r"\w+", b.lower()))
    if not a_set or not b_set:
        return 0.0
    intersection = a_set & b_set
    return len(intersection) / min(len(a_set), len(b_set))


def is_duplicate_by_title(new_title: str, existing_titles: list[str], threshold: float = 0.85) -> bool:
    for title in existing_titles:
        if title_similarity(new_title, title) >= threshold:
            return True
    return False


def filter_news_by_date(
    items: list[dict],
    target_date_str: str,
) -> list[dict]:
    filtered = []
    for item in items:
        pub_date = item.get("published_at", "")
        if pub_date and target_date_str in pub_date:
            filtered.append(item)
    return filtered
