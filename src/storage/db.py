import sqlite3
from pathlib import Path
from contextlib import contextmanager
from .models import NewsItem


class Database:
    def __init__(self, db_path: str = "data/news.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS news (
                    id TEXT PRIMARY KEY,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    original_text TEXT,
                    source TEXT NOT NULL,
                    published_at TEXT,
                    collected_at TEXT NOT NULL,
                    translated_title TEXT,
                    translated_text TEXT,
                    summary TEXT,
                    keywords TEXT,
                    categories TEXT DEFAULT '[]',
                    regions TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'pending',
                    processed_at TEXT,
                    error_message TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON news(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_collected_at ON news(collected_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON news(source)")

            # migrate old columns if they exist
            try:
                conn.execute("ALTER TABLE news ADD COLUMN categories TEXT DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE news ADD COLUMN regions TEXT DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass

    def url_exists(self, url: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM news WHERE url = ?", (url,)).fetchone()
            return row is not None

    def insert_news(self, item: NewsItem):
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO news
                   (id, url, title, original_text, source, published_at, collected_at,
                    translated_title, translated_text, summary, keywords,
                    categories, regions, status, processed_at, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.id, item.url, item.title, item.original_text, item.source,
                    item.published_at, item.collected_at,
                    item.translated_title, item.translated_text, item.summary,
                    item.keywords, item.categories, item.regions,
                    item.status, item.processed_at, item.error_message,
                ),
            )

    def get_pending_items(self, limit: int = 50) -> list[NewsItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM news WHERE status = 'pending' ORDER BY collected_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_item(r) for r in rows]

    def update_item(self, item: NewsItem):
        with self._conn() as conn:
            conn.execute(
                """UPDATE news SET
                   translated_title=?, translated_text=?, summary=?, keywords=?,
                   categories=?, regions=?, status=?, processed_at=?, error_message=?
                   WHERE id=?""",
                (
                    item.translated_title, item.translated_text, item.summary,
                    item.keywords, item.categories, item.regions,
                    item.status, item.processed_at, item.error_message, item.id,
                ),
            )

    def get_processed_by_date(self, date_str: str) -> list[NewsItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM news WHERE status = 'processed' AND date(collected_at) = ? ORDER BY collected_at DESC",
                (date_str,),
            ).fetchall()
            return [self._row_to_item(r) for r in rows]

    def get_stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM news WHERE status='pending'").fetchone()[0]
            processed = conn.execute("SELECT COUNT(*) FROM news WHERE status='processed'").fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM news WHERE status='failed'").fetchone()[0]
            return {"total": total, "pending": pending, "processed": processed, "failed": failed}

    @staticmethod
    def _row_to_item(row) -> NewsItem:
        return NewsItem(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            original_text=row["original_text"] or "",
            source=row["source"],
            published_at=row["published_at"] or "",
            collected_at=row["collected_at"],
            translated_title=row.get("translated_title") or "",
            translated_text=row.get("translated_text") or "",
            summary=row.get("summary") or "",
            keywords=row.get("keywords") or "[]",
            categories=row.get("categories") or "[]",
            regions=row.get("regions") or "[]",
            status=row.get("status") or "pending",
            processed_at=row.get("processed_at") or "",
            error_message=row.get("error_message") or "",
        )
