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
from src.storage.models import NewsItem, CATEGORY_LABELS, REGION_LABELS
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

REGION_ORDER = ["China", "Asia", "Europe", "NorthAmerica", "SouthAmerica", "MiddleEast", "Africa", "Oceania", "Global"]


def create_app(config: dict) -> FastAPI:
    app = FastAPI(title="空运新闻速递", version="1.0.0")
    db = Database()
    scraper = Scraper(config)

    template_dir = Path(__file__).parent / "templates"
    jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))
    jinja_env.globals["CATEGORY_LABELS"] = CATEGORY_LABELS
    jinja_env.globals["REGION_LABELS"] = REGION_LABELS
    jinja_env.globals["REGION_ORDER"] = REGION_ORDER
    jinja_env.globals["CATEGORY_ORDER"] = CATEGORY_ORDER

    def render_template(name: str, context: dict) -> HTMLResponse:
        template = jinja_env.get_template(name)
        return HTMLResponse(template.render(**context))

    output_dir = Path(config.get("output", {}).get("dir", "./output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/digests", StaticFiles(directory=str(output_dir.resolve())), name="digests")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        today = datetime.now().strftime("%Y-%m-%d")
        items = db.get_processed_by_date(today)

        if not items:
            recent = _get_recent_news(db, limit=30)
            return render_template("index.html", {
                "request": request, "date_str": today,
                "date_display": datetime.now().strftime("%Y年%m月%d日"),
                "items": [], "recent_items": recent, "total_count": 0,
                "categories": [], "all_keywords": [], "sources": "",
                "today_has_digest": False,
            })

        return render_template("index.html", {
            "request": request, "date_str": today,
            "date_display": datetime.now().strftime("%Y年%m月%d日"),
            "items": items, "recent_items": [], "total_count": len(items),
            "categories": _build_categories(items),
            "all_keywords": _build_keyword_cloud(items),
            "sources": ", ".join(sorted(set(i.source for i in items))),
            "today_has_digest": True,
        })

    @app.get("/history", response_class=HTMLResponse)
    async def history(request: Request):
        digest_files = []
        for f in sorted(output_dir.glob("daily_*.html"), reverse=True):
            date_str = f.stem.replace("daily_", "")
            try:
                display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y年%m月%d日")
            except ValueError:
                display = date_str
            digest_files.append({"date": date_str, "display": display, "filename": f.name})
        return render_template("history.html", {"request": request, "digest_files": digest_files})

    @app.get("/search", response_class=HTMLResponse)
    async def search_page(request: Request):
        return render_template("search.html", {"request": request, "results": None, "query": "", "total": 0})

    @app.get("/api/search")
    async def api_search(q: str = Query(""), category: str = Query(""), region: str = Query(""), page: int = Query(1), size: int = Query(20)):
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        conditions = ["status = 'processed'"]
        params = []
        if q:
            conditions.append("(title LIKE ? OR translated_title LIKE ? OR summary LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like])
        if category:
            conditions.append("categories LIKE ?")
            params.append(f'%"{category}"%')
        if region:
            conditions.append("regions LIKE ?")
            params.append(f'%"{region}"%')
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
            item = Database._row_to_item(row)
            results.append({
                "id": item.id, "url": item.url, "title": item.title,
                "translated_title": item.translated_title, "summary": item.summary,
                "keywords": item.get_keywords_list(),
                "category_labels": item.get_category_labels(),
                "region_list": item.get_regions_list(),
                "region_labels": item.get_region_labels(),
                "source": item.source, "published_at": item.published_at,
            })
        return {"results": results, "total": total, "page": page, "size": size, "pages": max(1, (total + size - 1) // size)}

    @app.get("/sources", response_class=HTMLResponse)
    async def sources_page(request: Request):
        return render_template("sources.html", {"request": request, "sources": config.get("sources", [])})

    @app.post("/api/sources")
    async def add_source(data: dict = Body(...)):
        try:
            import yaml
            config_path = Path("config.yaml")
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            cfg.setdefault("sources", []).append(data)
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            return JSONResponse({"status": "ok", "message": "来源已添加，重启服务后生效"})
        except Exception as e:
            return JSONResponse({"detail": str(e)}, status_code=400)

    @app.delete("/api/sources/{index}")
    async def delete_source(index: int):
        try:
            import yaml
            config_path = Path("config.yaml")
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            if 0 <= index < len(cfg.get("sources", [])):
                removed = cfg["sources"].pop(index)
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                return JSONResponse({"status": "ok", "message": f"已删除 {removed.get('name', '')}"})
            return JSONResponse({"detail": "Index out of range"}, status_code=400)
        except Exception as e:
            return JSONResponse({"detail": str(e)}, status_code=400)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings(request: Request):
        key = load_api_key()
        masked = ""
        if key and len(key) > 10:
            masked = key[:6] + "*" * (len(key) - 10) + key[-4:]
        return render_template("settings.html", {
            "request": request, "has_key": bool(key), "masked_key": masked,
            "key_prefix": key[:6] if key else "", "key_suffix": key[-4:] if key else "",
        })

    @app.get("/api/settings/api-key")
    async def get_api_key():
        key = load_api_key()
        masked = key[:6] + "*" * (len(key) - 10) + key[-4:] if key and len(key) > 10 else key
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

    @app.get("/admin", response_class=HTMLResponse)
    async def admin(request: Request):
        stats = db.get_stats()
        return render_template("admin.html", {"request": request, "stats": stats})

    @app.post("/api/trigger/collect")
    async def trigger_collect():
        def _run():
            lookback = config.get("scraping", {}).get("lookback_days", 1)
            for source in config.get("sources", []):
                if not source.get("enabled", True):
                    continue
                items = scraper.scrape_list(source, lookback_days=lookback)
                content_sel = source.get("article_selector", {}).get("content", "")
                for item in items:
                    if db.url_exists(item["url"]):
                        continue
                    body = scraper.scrape_article(item["url"], content_sel) if content_sel else ""
                    news = NewsItem(url=item["url"], title=item["title"],
                                    original_text=body or item.get("summary", ""),
                                    source=item["source"], published_at=item.get("published_at", ""))
                    db.insert_news(news)
        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started", "message": "全流程已触发，完成后自动刷新页面"})

    @app.post("/api/trigger/backfill")
    async def trigger_backfill():
        def _run():
            since_date = "2026-05-01"
            for source in config.get("sources", []):
                if not source.get("enabled", True):
                    continue
                pagination = source.get("pagination", {})
                if not pagination.get("pattern"):
                    continue
                items = scraper.scrape_pages(source, since_date=since_date, max_pages=50)
                content_sel = source.get("article_selector", {}).get("content", "")
                for item in items:
                    if db.url_exists(item["url"]):
                        continue
                    body = scraper.scrape_article(item["url"], content_sel) if content_sel else ""
                    news = NewsItem(url=item["url"], title=item["title"],
                                    original_text=body or item.get("summary", ""),
                                    source=item["source"], published_at=item.get("published_at", ""))
                    db.insert_news(news)
        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started"})

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
    return [Database._row_to_item(r) for r in rows]


def _build_categories(items: list) -> list:
    cats = []
    for cat_id, cat_name in CATEGORY_ORDER:
        cat_items = [i for i in items if cat_id in i.get_categories_list()]
        cats.append((cat_id, cat_name, cat_items))
    return cats


def _build_keyword_cloud(items: list) -> list:
    counter = Counter()
    for item in items:
        for kw in item.get_keywords_list():
            counter[kw] += 1
    total = sum(counter.values()) or 1
    result = []
    for kw, count in counter.most_common(30):
        size = max(12, min(22, 12 + int(10 * count / total * 20)))
        result.append((kw, size))
    return result
