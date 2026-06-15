import threading
from datetime import datetime
from pathlib import Path
from collections import Counter
import json

from fastapi import FastAPI, Request, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader

from src.storage.db import Database
from src.storage.models import NewsItem
from src.collector.scraper import Scraper
from src.processor.pipeline import ProcessingPipeline
from src.reporter.digest import DigestReporter
from src.utils.logger import setup_logger
from src.utils.key_store import load_api_key, save_api_key

logger = setup_logger("web")

CATEGORY_ORDER = [
    ("1", "运价"), ("2", "运力"), ("3", "航线"), ("4", "政策法规"),
    ("5", "企业动态"), ("6", "市场报告"), ("7", "技术与可持续"), ("8", "其他"),
]

CATEGORY_LABELS = dict(CATEGORY_ORDER)

CHINA_LABELS = {"high": "★ 中国相关", "medium": "☆ 亚太相关", "low": "", "none": ""}


def create_app(config: dict) -> FastAPI:
    app = FastAPI(title="AirCargoNews Digest", version="1.0.0")
    db = Database()
    scraper = Scraper(config)

    template_dir = Path(__file__).parent / "templates"
    jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))
    jinja_env.globals["CATEGORY_LABELS"] = CATEGORY_LABELS
    jinja_env.globals["CHINA_LABELS"] = CHINA_LABELS

    def render_template(name: str, context: dict) -> HTMLResponse:
        template = jinja_env.get_template(name)
        return HTMLResponse(template.render(**context))

    output_dir = Path(config.get("output", {}).get("dir", "./output"))
    app.mount("/digests", StaticFiles(directory=str(output_dir.resolve())), name="digests")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        today = datetime.now().strftime("%Y-%m-%d")
        items = db.get_processed_by_date(today)

        if not items:
            recent = _get_recent_news(db, limit=30)
            return render_template("index.html", {
                "request": request,
                "date_str": today,
                "date_display": datetime.now().strftime("%Y年%m月%d日"),
                "items": [],
                "recent_items": recent,
                "total_count": 0,
                "headlines": [],
                "categories": [],
                "all_keywords": [],
                "china_count": 0,
                "sources": "",
                "today_has_digest": False,
            })

        return render_template("index.html", {
            "request": request,
            "date_str": today,
            "date_display": datetime.now().strftime("%Y年%m月%d日"),
            "items": items,
            "recent_items": [],
            "total_count": len(items),
            "headlines": _select_headlines(items)[0],
            "categories": _build_categories(items),
            "all_keywords": _build_keyword_cloud(items),
            "china_count": sum(1 for i in items if i.china_relevance in ("high", "medium")),
            "china_high": sum(1 for i in items if i.china_relevance == "high"),
            "china_medium": sum(1 for i in items if i.china_relevance == "medium"),
            "sources": ", ".join(sorted(set(i.source for i in items))),
            "today_has_digest": True,
        })

    @app.get("/history", response_class=HTMLResponse)
    async def history(request: Request):
        output_pattern = config.get("output", {}).get("filename_pattern", "daily_{date}.html")
        digest_files = []
        for f in sorted(output_dir.glob("daily_*.html"), reverse=True):
            date_str = f.stem.replace("daily_", "")
            digest_files.append({
                "date": date_str,
                "display": datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y年%m月%d日"),
                "filename": f.name,
            })

        return render_template("history.html", {
            "request": request,
            "digest_files": digest_files,
        })

    @app.get("/settings", response_class=HTMLResponse)
    async def settings(request: Request):
        key = load_api_key()
        masked = ""
        prefix = ""
        suffix = ""
        if key:
            prefix = key[:6]
            suffix = key[-4:]
            masked = key[:6] + "*" * (len(key) - 10) + key[-4:] if len(key) > 10 else key
        return render_template("settings.html", {
            "request": request,
            "has_key": bool(key),
            "masked_key": masked,
            "key_prefix": prefix,
            "key_suffix": suffix,
        })

    @app.get("/api/settings/api-key")
    async def get_api_key():
        key = load_api_key()
        masked = ""
        if key:
            masked = key[:6] + "*" * (len(key) - 10) + key[-4:] if len(key) > 10 else key
        return JSONResponse({"masked_key": masked, "has_key": bool(key)})

    @app.post("/api/settings/api-key")
    async def set_api_key(data: dict = Body(...)):
        key = data.get("api_key", "").strip()
        if not key:
            save_api_key("")
            return JSONResponse({"status": "ok", "message": "API Key 已清除"})
        if not key.startswith("sk-"):
            return JSONResponse({"detail": "API Key 格式无效，应以 sk- 开头"}, status_code=400)
        save_api_key(key)
        return JSONResponse({"status": "ok", "message": f"API Key 已保存 (sk-...{key[-4:]})"})

    @app.get("/search", response_class=HTMLResponse)
    async def search_page(request: Request):
        return render_template("search.html", {
            "request": request,
            "results": None,
            "query": "",
            "total": 0,
        })

    @app.get("/api/search")
    async def api_search(q: str = Query(""), category: str = Query(""), china: str = Query(""), page: int = Query(1), size: int = Query(20)):
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row

        conditions = ["status = 'processed'"]
        params = []

        if q:
            conditions.append("(title LIKE ? OR translated_title LIKE ? OR summary LIKE ? OR translated_text LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like, like])

        if category:
            conditions.append("category = ?")
            params.append(category)

        if china:
            conditions.append("china_relevance = ?")
            params.append(china)

        where = " AND ".join(conditions)

        count_row = conn.execute(f"SELECT COUNT(*) FROM news WHERE {where}", params).fetchone()
        total = count_row[0] if count_row else 0

        offset = (page - 1) * size
        rows = conn.execute(
            f"SELECT * FROM news WHERE {where} ORDER BY collected_at DESC LIMIT ? OFFSET ?",
            params + [size, offset]
        ).fetchall()
        conn.close()

        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "url": row["url"],
                "title": row["title"],
                "translated_title": row["translated_title"],
                "summary": row["summary"],
                "keywords": json.loads(row["keywords"]) if row["keywords"] else [],
                "category": row["category"],
                "category_label": CATEGORY_LABELS.get(row["category"], "其他"),
                "china_relevance": row["china_relevance"],
                "china_label": CHINA_LABELS.get(row["china_relevance"], ""),
                "source": row["source"],
                "published_at": row["published_at"],
            })

        return {"results": results, "total": total, "page": page, "size": size, "pages": max(1, (total + size - 1) // size)}

    @app.get("/admin", response_class=HTMLResponse)
    async def admin(request: Request):
        stats = db.get_stats()
        return render_template("admin.html", {
            "request": request,
            "stats": stats,
        })

    @app.post("/api/trigger/collect")
    async def trigger_collect():
        def _run():
            lookback = config.get("scraping", {}).get("lookback_days", 1)
            total_new = 0
            for source in config.get("sources", []):
                if not source.get("enabled", True):
                    continue
                items = scraper.scrape_list(source, lookback_days=lookback)
                content_sel = source.get("article_selector", {}).get("content", "")
                for item in items:
                    if db.url_exists(item["url"]):
                        continue
                    body = scraper.scrape_article(item["url"], content_sel) if content_sel else ""
                    news = NewsItem(
                        url=item["url"], title=item["title"],
                        original_text=body or item.get("summary", ""),
                        source=item["source"], published_at=item.get("published_at", ""),
                    )
                    db.insert_news(news)
                    total_new += 1
            logger.info("Web trigger collection done: %d new items", total_new)

        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started", "message": "Collection triggered in background"})

    @app.post("/api/trigger/process")
    async def trigger_process():
        def _run():
            pipeline = ProcessingPipeline(config, db)
            stats = pipeline.process_pending()
            logger.info("Web trigger processing done: %s", stats)
        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started", "message": "Processing triggered in background"})

    @app.post("/api/trigger/backfill")
    async def trigger_backfill():
        def _run():
            since_date = "2026-05-01"
            max_pages = 50
            for source in config.get("sources", []):
                if not source.get("enabled", True):
                    continue
                pagination = source.get("pagination", {})
                if not pagination.get("pattern"):
                    continue
                items = scraper.scrape_pages(source, since_date=since_date, max_pages=max_pages)
                content_sel = source.get("article_selector", {}).get("content", "")
                for item in items:
                    if db.url_exists(item["url"]):
                        continue
                    body = scraper.scrape_article(item["url"], content_sel) if content_sel else ""
                    news = NewsItem(
                        url=item["url"], title=item["title"],
                        original_text=body or item.get("summary", ""),
                        source=item["source"], published_at=item.get("published_at", ""),
                    )
                    db.insert_news(news)
            logger.info("Web trigger backfill done")
        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started", "message": "Backfill triggered (since 2026-05-01)"})
    async def trigger_report():
        def _run():
            reporter = DigestReporter(config, db)
            reporter.generate()
        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started", "message": "Report generation triggered in background"})

    @app.post("/api/trigger/run")
    async def trigger_run():
        def _run():
            lookback = config.get("scraping", {}).get("lookback_days", 1)
            total_new = 0
            for source in config.get("sources", []):
                if not source.get("enabled", True):
                    continue
                items = scraper.scrape_list(source, lookback_days=lookback)
                content_sel = source.get("article_selector", {}).get("content", "")
                for item in items:
                    if db.url_exists(item["url"]):
                        continue
                    body = scraper.scrape_article(item["url"], content_sel) if content_sel else ""
                    news = NewsItem(
                        url=item["url"], title=item["title"],
                        original_text=body or item.get("summary", ""),
                        source=item["source"], published_at=item.get("published_at", ""),
                    )
                    db.insert_news(news)
                    total_new += 1
            pipeline = ProcessingPipeline(config, db)
            pipeline.process_pending()
            reporter = DigestReporter(config, db)
            reporter.generate()
            logger.info("Web trigger full run done")
        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started", "message": "Full pipeline triggered in background"})

    @app.get("/api/stats")
    async def api_stats():
        return JSONResponse(db.get_stats())

    return app


def _get_recent_news(db: Database, limit: int = 30) -> list:
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM news WHERE status='processed' ORDER BY collected_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    items = []
    for row in rows:
        item = Database._row_to_item(row)
        items.append(item)
    return items


def _select_headlines(items: list) -> tuple:
    china_high = [i for i in items if i.china_relevance == "high"]
    remaining = [i for i in items if i.china_relevance != "high"]
    headlines = china_high[:5]
    if len(headlines) < 3:
        for item in remaining[: (5 - len(headlines))]:
            headlines.append(item)
    rest = [i for i in items if i not in headlines]
    return headlines, rest


def _build_categories(items: list) -> list:
    cats = []
    for cat_id, cat_name in CATEGORY_ORDER:
        cat_items = [i for i in items if i.category == cat_id]
        cat_items.sort(key=lambda x: (0 if x.china_relevance == "high" else 1 if x.china_relevance == "medium" else 2))
        cats.append((cat_id, cat_name, cat_items))
    return cats


def _build_keyword_cloud(items: list) -> list:
    counter = Counter()
    for item in items:
        for kw in item.get_keywords_list():
            counter[kw] += 1
    total = sum(counter.values()) or 1
    result = []
    for kw, count in counter.most_common(40):
        size = max(12, min(24, 12 + int(12 * count / total * 20)))
        result.append((kw, size))
    return result
