import json
import time
from datetime import datetime

from src.processor.llm_client import LLMClient
from src.storage.models import NewsItem
from src.storage.db import Database
from src.utils.logger import setup_logger

logger = setup_logger("pipeline")


class ProcessingPipeline:
    def __init__(self, config: dict, db: Database):
        self.llm = LLMClient(config)
        self.db = db
        self.batch_size = config.get("llm", {}).get("batch_size", 5)

    def process_pending(self) -> dict:
        items = self.db.get_pending_items(limit=self.batch_size * 10)
        if not items:
            logger.info("No pending items to process")
            return {"total": 0, "processed": 0, "failed": 0, "skipped": 0}

        stats = {"total": len(items), "processed": 0, "failed": 0, "skipped": 0}

        for i, item in enumerate(items):
            logger.info("Processing [%d/%d]: %s", i + 1, len(items), item.title[:60])
            try:
                content = item.original_text
                if not content or len(content) < 50:
                    logger.warning("Skipping %s: insufficient content", item.title)
                    item.status = "skipped"
                    self.db.update_item(item)
                    stats["skipped"] += 1
                    continue

                result = self.llm.process_news(
                    title=item.title,
                    content=content,
                    url=item.url,
                    source=item.source,
                )

                if result:
                    item.translated_title = result.get("translated_title", "")
                    item.translated_text = result.get("translated_text", "")
                    item.summary = result.get("summary", "")
                    item.core_extract = result.get("core_extract", "")
                    item.keywords = json.dumps(result.get("keywords", [])[:5], ensure_ascii=False)
                    item.categories = json.dumps(result.get("categories", []), ensure_ascii=False)
                    item.regions = json.dumps(result.get("regions", []), ensure_ascii=False)
                    item.status = "processed"
                    item.processed_at = datetime.now().isoformat()
                    stats["processed"] += 1
                    logger.info("Processed: %s → %s", item.title[:40], item.translated_title[:40])
                else:
                    item.status = "failed"
                    item.error_message = "LLM returned no result after retries"
                    stats["failed"] += 1

                self.db.update_item(item)
                time.sleep(0.5)

            except Exception as e:
                logger.error("Error processing item %s: %s", item.id, e)
                item.status = "failed"
                item.error_message = str(e)[:500]
                self.db.update_item(item)
                stats["failed"] += 1

        return stats
