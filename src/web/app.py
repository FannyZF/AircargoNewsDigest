import threading
from datetime import datetime
from pathlib import Path
from collections import Counter
import json

from fastapi import FastAPI, Request, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import Environment, FileSystemLoader

from src.storage.db import Database
from src.storage.models import NewsItem, CATEGORY_LABELS, REGION_LABELS
from src.collector.scraper import Scraper
from src.processor.pipeline import ProcessingPipeline
from src.reporter.digest import DigestReporter
from src.utils.logger import setup_logger
from src.utils.key_store import load_api_key, save_api_key
from src.utils.schedule_store import load_schedule, save_schedule
from src.utils.subscription_store import add_subscriber, remove_subscriber, get_active_subscribers, load_subscribers
from src.utils.mailer import save_smtp_config, load_smtp_config, send_digest_email

logger = setup_logger("web")

CATEGORY_ORDER = [
    ("1", "运价"), ("2", "运力"), ("3", "航线"), ("4", "政策法规"),
    ("5", "企业动态"), ("6", "市场报告"), ("7", "技术与可持续"), ("8", "其他"),
]

REGION_ORDER = ["China", "Asia", "Europe", "NorthAmerica", "SouthAmerica", "MiddleEast", "Africa", "Oceania", "Global"]


def create_app(config: dict) -> FastAPI:
    app = FastAPI(title="空运新闻速递", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
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

    @app.delete("/api/history/{date_str}")
    async def delete_digest(date_str: str):
        f = output_dir / f"daily_{date_str}.html"
        if f.exists():
            f.unlink()
            return JSONResponse({"status": "ok", "message": f"已删除 {date_str} 日报"})
        return JSONResponse({"detail": "文件不存在"}, status_code=404)

    @app.post("/api/history/regenerate/{date_str}")
    async def regenerate_digest(date_str: str):
        def _run():
            reporter = DigestReporter(config, db)
            reporter.generate(date_str, collection_date=date_str)
        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started", "message": f"正在重新生成 {date_str} 日报"})

    @app.post("/api/history/push/{date_str}")
    async def push_digest(date_str: str):
        f = output_dir / f"daily_{date_str}.html"
        if not f.exists():
            return JSONResponse({"detail": f"{date_str} 日报文件不存在"}, status_code=404)
        smtp_cfg = load_smtp_config()
        if not smtp_cfg.get("host"):
            return JSONResponse({"detail": "SMTP 未配置，请先在设置页面配置邮件服务器"}, status_code=400)
        sub_count = len(get_active_subscribers())
        if sub_count == 0:
            return JSONResponse({"detail": "没有订阅者，请先在订阅页面添加"}, status_code=400)
        def _run():
            result = send_digest_email(get_active_subscribers(), f, date_str)
            logger.info("Push result: %s", result)
        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started", "message": f"正在推送 {date_str} 日报给 {sub_count} 位订阅者"})

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

    @app.get("/subscribe", response_class=HTMLResponse)
    async def subscribe_page(request: Request):
        count = len(get_active_subscribers())
        return render_template("subscribe.html", {"request": request, "count": count})

    @app.post("/api/sources/detect")
    async def detect_selectors(data: dict = Body(...)):
        url = data.get("url", "").strip()
        if not url:
            return JSONResponse({"detail": "URL is required"}, status_code=400)

        try:
            from bs4 import BeautifulSoup
            import re

            html = scraper._fetch(url)
            if not html:
                return JSONResponse({"detail": "抓取页面失败，请检查 URL 是否正确"}, status_code=400)

            soup = BeautifulSoup(html, "lxml")

            for t in soup.select("script, style, nav, footer, noscript, iframe"):
                t.decompose()

            # find news containers by common patterns
            container_candidates = []
            container_keywords = ["post", "article", "news", "entry", "item", "story", "summary", "card", "media", "list", "row", "story-block", "headline"]

            for el in soup.select("article, div, li"):
                links = el.select("a[href]")
                if not links:
                    continue
                cls_str = " ".join(el.get("class", [])).lower() if el.get("class") else ""
                tag_lower = el.get("id", "").lower()
                combined = f"{cls_str} {tag_lower}"
                if any(kw in combined for kw in container_keywords):
                    container_candidates.append(el)

            # fallback: find div/li with both a link and a date-like element
            if not container_candidates:
                for el in soup.select("div, li"):
                    if el.select("a[href]") and (el.select_one("time, [datetime]") or re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", el.get_text())):
                        container_candidates.append(el)

            # fallback: any article tag
            if not container_candidates:
                articles = soup.select("article")
                if articles:
                    container_candidates = articles[:1]

            if not container_candidates:
                return JSONResponse({"detail": "无法识别新闻列表结构，请手动填写 CSS 选择器", "status": "error"}, status_code=400)

            # pick the best container: most child links + has date patterns
            best_container = None
            best_score = 0
            for el in container_candidates:
                links = el.select("a[href]")
                text = el.get_text()
                score = len(links) * 2
                if re.search(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", text):
                    score += 5
                if el.select_one("time, [datetime]"):
                    score += 3
                if score > best_score:
                    best_score = score
                    best_container = el

            if not best_container:
                return JSONResponse({"detail": "无法自动识别新闻列表结构，请手动填写"}, status_code=400)

            tag = best_container.name
            cls = " ".join(best_container.get("class", []))
            container_sel = f"{tag}.{cls.replace(' ', '.')}" if cls else tag

            # count same-type containers
            all_containers = soup.select(container_sel)
            if len(all_containers) < 3 and best_container.parent and tag:
                try:
                    siblings = best_container.parent.select(f"> {tag}")
                    if len(siblings) > len(all_containers):
                        all_containers = siblings
                        container_sel = tag
                except Exception:
                    pass

            # title selector
            title_sel = ""
            for sel in ["h2 a", "h3 a", "h4 a", "a[class*=title]", "a[class*=headline]", "h2.entry-title a", "h3.entry-title a"]:
                if best_container.select_one(sel):
                    title_sel = sel
                    break
            if not title_sel:
                headings = best_container.select("h1 a, h2 a, h3 a, h4 a")
                if headings:
                    title_sel = f"{headings[0].parent.name} a"
                else:
                    links = best_container.select("a[href]")
                    if links:
                        # pick the first link that has substantial text
                        for a in links:
                            txt = a.get_text(strip=True)
                            if len(txt) > 15:
                                candidates = best_container.select(f"a")
                                title_sel = "a" if len(candidates) == 1 else f"{a.name}"
                                # use direct child + element name
                                if a.get("class"):
                                    title_sel = f"a.{' '.join(a.get('class', []))[:0].replace(' ', '.')}"
                                if not title_sel or title_sel == "a":
                                    title_sel = f"{a.parent.name} a" if a.parent else "a"
                                break

            # date selector
            date_sel = ""
            date_attr = "datetime"
            date_regex = ""
            time_el = best_container.select_one("time[datetime]")
            if time_el:
                date_sel = "time"
                if time_el.parent and time_el.parent.get("class"):
                    pcls = ".".join(time_el.parent.get("class", []))
                    date_sel = f"div.{pcls} time, span.{pcls} time, .{pcls} time"
            else:
                for dsel in ["time", ".date", ".post-date", ".entry-date", ".meta time", ".small", "span.date", "[datetime]"]:
                    if best_container.select_one(dsel):
                        date_sel = dsel
                        break
                if not date_sel:
                    date_sel = "time, [datetime], .date"

            # summary
            summary_sel = ""
            for ssel in ["p.excerpt", "p.summary", "div.excerpt", "div.entry-summary", "div.summary", ".entry-content p", ".post-excerpt", "p"]:
                if best_container.select_one(ssel):
                    summary_sel = ssel
                    break

            # content selector for detail pages
            content_sel = "div.entry-content, div.post-content, article, div.article-body, div.content, div.single-content, div.story-content"

            # pagination
            pagination = ""
            pager_link = soup.select_one("a.page-numbers, a[class*=page], .pagination a, .nav-links a")
            if pager_link:
                href = pager_link.get("href", "")
                m = re.search(r"page/(\d+)", href)
                if m:
                    pagination = "/page/{page}/"
                else:
                    m = re.search(r"[?&]paged?=(\d+)", href)
                    if m:
                        pagination = "?page={page}"

            return JSONResponse({
                "status": "ok",
                "url": url,
                "container_count": len(all_containers),
                "suggestions": {
                    "list_container": container_sel,
                    "title": title_sel,
                    "link": title_sel,
                    "date": date_sel,
                    "date_attr": date_attr,
                    "date_regex": date_regex,
                    "summary": summary_sel,
                    "content": content_sel,
                    "pagination": pagination,
                }
            })

        except Exception as e:
            logger.error("Auto-detect failed: %s", e)
            return JSONResponse({"detail": f"探测失败: {str(e)}"}, status_code=400)

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
        sched = load_schedule()
        return render_template("settings.html", {
            "request": request, "has_key": bool(key), "masked_key": masked,
            "key_prefix": key[:6] if key else "", "key_suffix": key[-4:] if key else "",
            "schedule_time": sched.get("time", "23:00"),
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

    @app.post("/api/settings/schedule")
    async def set_schedule(data: dict = Body(...)):
        time_str = data.get("time", "").strip()
        if not time_str or ":" not in time_str:
            return JSONResponse({"detail": "时间格式无效，请使用 HH:MM"}, status_code=400)
        save_schedule(time_str)
        return JSONResponse({"status": "ok", "message": f"定时已更新: 每天 {time_str} (重启服务后生效)"})

    @app.post("/api/settings/smtp")
    async def set_smtp(data: dict = Body(...)):
        host = data.get("host", "").strip()
        port = int(data.get("port", 465))
        user = data.get("user", "").strip()
        password = data.get("password", "").strip()
        sender = data.get("sender", "").strip()
        if not host or not user or not password or not sender:
            return JSONResponse({"detail": "所有 SMTP 字段必填"}, status_code=400)
        save_smtp_config(host, port, user, password, sender)
        return JSONResponse({"status": "ok", "message": "SMTP 配置已保存"})

    @app.get("/api/subscribe/count")
    async def subscribe_count():
        return JSONResponse({"count": len(get_active_subscribers()), "subscribers": load_subscribers()})

    @app.post("/api/subscribe")
    async def subscribe(data: dict = Body(...)):
        email = data.get("email", "").strip().lower()
        if not email or "@" not in email:
            return JSONResponse({"detail": "邮箱地址无效"}, status_code=400)
        ok = add_subscriber(email)
        if ok:
            return JSONResponse({"status": "ok", "message": f"订阅成功: {email}"})
        return JSONResponse({"detail": "该邮箱已订阅"}, status_code=400)

    @app.post("/api/unsubscribe")
    async def unsubscribe(data: dict = Body(...)):
        email = data.get("email", "").strip().lower()
        ok = remove_subscriber(email)
        if ok:
            return JSONResponse({"status": "ok", "message": f"已退订: {email}"})
        return JSONResponse({"detail": "未找到该邮箱"}, status_code=400)

    # Public API for external websites / WeChat
    @app.get("/api/public/subscribe")
    async def public_subscribe_get(email: str = Query("")):
        email = email.strip().lower()
        if not email or "@" not in email:
            return JSONResponse({"code": 1, "msg": "邮箱地址无效"}, status_code=400)
        ok = add_subscriber(email)
        if ok:
            return JSONResponse({"code": 0, "msg": f"订阅成功: {email}"})
        return JSONResponse({"code": 2, "msg": "该邮箱已订阅"})

    @app.get("/api/public/unsubscribe")
    async def public_unsubscribe_get(email: str = Query("")):
        email = email.strip().lower()
        if not email or "@" not in email:
            return JSONResponse({"code": 1, "msg": "邮箱地址无效"}, status_code=400)
        ok = remove_subscriber(email)
        if ok:
            return JSONResponse({"code": 0, "msg": f"已退订: {email}"})
        return JSONResponse({"code": 2, "msg": "未找到该邮箱"})

    @app.get("/s", response_class=HTMLResponse)
    async def standalone_subscribe(request: Request):
        count = len(get_active_subscribers())
        return render_template("standalone_sub.html", {"request": request, "count": count})

    @app.get("/admin", response_class=HTMLResponse)
    async def admin(request: Request):
        stats = db.get_stats()
        return render_template("admin.html", {"request": request, "stats": stats})

    @app.post("/api/trigger/collect")
    async def trigger_collect():
        logger.info("Web trigger: collect")
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
        return JSONResponse({"status": "started", "message": "新闻抓取已触发，请稍后刷新"})

    @app.post("/api/trigger/process")
    async def trigger_process():
        logger.info("Web trigger: process")
        def _run():
            pipeline = ProcessingPipeline(config, db)
            pipeline.process_pending()
        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started", "message": "LLM 处理已触发，请稍后刷新"})

    @app.post("/api/trigger/report")
    async def trigger_report():
        logger.info("Web trigger: report")
        def _run():
            reporter = DigestReporter(config, db)
            reporter.generate()
        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started", "message": "日报生成已触发，请稍后刷新"})

    @app.post("/api/trigger/run")
    async def trigger_run():
        logger.info("Web trigger: run (full pipeline)")
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
            ProcessingPipeline(config, db).process_pending()
            DigestReporter(config, db).generate()
        threading.Thread(target=_run, daemon=True).start()
        return JSONResponse({"status": "started", "message": "全流程已触发，完成后自动刷新页面"})

    @app.post("/api/trigger/restart")
    async def trigger_restart():
        def _restart():
            import time, os, sys
            time.sleep(1)
            os.execv(sys.executable, [sys.executable] + sys.argv)
        threading.Thread(target=_restart, daemon=True).start()
        return JSONResponse({"status": "started", "message": "服务正在重启..."})

    @app.post("/api/trigger/backfill")
    async def trigger_backfill():
        logger.info("Web trigger: backfill (since 2026-05-01)")
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
