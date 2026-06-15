import re
import time
import random
from datetime import datetime, date, timedelta

import httpx
from bs4 import BeautifulSoup

from src.collector.dedup import normalize_url
from src.utils.logger import setup_logger

logger = setup_logger("scraper")


class Scraper:
    def __init__(self, config: dict):
        self.scraping_cfg = config.get("scraping", {})
        self.user_agents = self.scraping_cfg.get("user_agents", [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ])
        self.timeout = self.scraping_cfg.get("timeout", 30)
        self.max_retries = self.scraping_cfg.get("max_retries", 3)
        self.request_interval = self.scraping_cfg.get("request_interval", 2)
        self._last_request = 0

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.request_interval:
            time.sleep(self.request_interval - elapsed)
        self._last_request = time.time()

    def _fetch(self, url: str) -> str | None:
        self._rate_limit()
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    resp = client.get(url, headers=self._headers())
                    resp.raise_for_status()
                    return resp.text
            except Exception as e:
                logger.warning("Fetch attempt %d/%d for %s failed: %s", attempt + 1, self.max_retries, url, e)
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
        logger.error("Failed to fetch %s after %d attempts", url, self.max_retries)
        return None

    def scrape_list(self, source: dict, lookback_days: int = 1) -> list[dict]:
        list_url = source["list_url"]
        base_url = source["base_url"]
        selectors = source["selectors"]
        name = source["name"]

        cutoff_date = datetime.now().date() - timedelta(days=lookback_days)

        logger.info("Scraping list from %s (%s), lookback=%d days (since %s)", name, list_url, lookback_days, cutoff_date)
        html = self._fetch(list_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        containers = soup.select(selectors["list_container"])
        logger.info("Found %d article containers for %s", len(containers), name)

        results = []
        for container in containers:
            try:
                item = self._parse_list_item(container, selectors, base_url, name)
                if item and self._is_within_range(item.get("published_at", ""), cutoff_date):
                    results.append(item)
            except Exception as e:
                logger.debug("Failed to parse list item: %s", e)
                continue

        logger.info("Collected %d matching articles from %s", len(results), name)
        return results

    def scrape_pages(self, source: dict, since_date: str, max_pages: int = 50) -> list[dict]:
        list_url = source["list_url"]
        base_url = source["base_url"]
        selectors = source["selectors"]
        name = source["name"]
        pagination = source.get("pagination", {"pattern": "/page/{page}/", "start": 1})

        cutoff_date = datetime.strptime(since_date, "%Y-%m-%d").date()
        all_results = []
        seen_urls = set()

        for page_num in range(pagination["start"], pagination["start"] + max_pages):
            if page_num == 1:
                page_url = list_url
            else:
                pattern = pagination["pattern"]
                page_url = base_url.rstrip("/") + pattern.format(page=page_num)

            logger.info("Scraping page %d: %s", page_num, page_url)
            html = self._fetch(page_url)
            if not html:
                logger.warning("Failed to fetch page %d, stopping", page_num)
                break

            soup = BeautifulSoup(html, "lxml")
            containers = soup.select(selectors["list_container"])

            if not containers:
                logger.info("No containers on page %d, stopping", page_num)
                break

            page_old = 0
            page_new = 0
            for container in containers:
                try:
                    item = self._parse_list_item(container, selectors, base_url, name)
                    if not item:
                        continue
                    url = item.get("url", "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    pub = item.get("published_at", "")
                    if self._is_within_range(pub, cutoff_date):
                        all_results.append(item)
                        page_new += 1
                    else:
                        page_old += 1
                except Exception as e:
                    logger.debug("Failed to parse list item: %s", e)
                    continue

            logger.info("Page %d: %d new, %d older than %s", page_num, page_new, page_old, since_date)
            if page_old > page_new and page_old > 5:
                logger.info("Most articles older than cutoff, stopping pagination")
                break

            self._rate_limit()

        logger.info("Backfill complete: %d total articles from %s", len(all_results), name)
        return all_results

    @staticmethod
    def _is_within_range(pub_date_str: str, cutoff_date) -> bool:
        if not pub_date_str:
            return False
        for fmt in [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%d %B %Y",
            "%B %d %Y",
            "%d %b %Y",
            "%b %d %Y",
        ]:
            try:
                parsed = datetime.strptime(pub_date_str[:19], fmt) if "T" in pub_date_str else datetime.strptime(pub_date_str, fmt)
                return parsed.date() >= cutoff_date
            except ValueError:
                continue
        return False

    def _parse_list_item(self, container, selectors: dict, base_url: str, source_name: str) -> dict | None:
        title_el = container.select_one(selectors["title"])
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        if not title:
            return None

        link_el = container.select_one(selectors["link"])
        if not link_el:
            link_el = container.find_parent("a") or container.find("a")
        if not link_el:
            return None

        href = link_el.get("href", "")
        if not href:
            return None

        if href.startswith("/"):
            href = base_url.rstrip("/") + href
        elif not href.startswith("http"):
            href = base_url.rstrip("/") + "/" + href.lstrip("/")

        url = normalize_url(href)

        pub_date = self._extract_date(container, selectors)

        summary = ""
        if selectors.get("summary"):
            summary_el = container.select_one(selectors["summary"])
            if summary_el:
                summary = summary_el.get_text(strip=True)

        return {
            "title": title,
            "url": url,
            "published_at": pub_date,
            "summary": summary,
            "source": source_name,
        }

    def _extract_date(self, container, selectors: dict) -> str:
        date_el = container.select_one(selectors["date"])
        if not date_el:
            return ""

        date_attr = selectors.get("date_attr", "datetime")
        if date_attr == "text":
            raw = date_el.get_text(strip=True)
            regex = selectors.get("date_regex", "")
            if regex:
                m = re.search(regex, raw)
                if m:
                    raw = m.group(1).strip()
            return self._normalize_date_text(raw)
        elif date_attr:
            return date_el.get(date_attr, "")

        return date_el.get_text(strip=True)

    @staticmethod
    def _normalize_date_text(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r",\s*", " ", text)
        try:
            for fmt in [
                "%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y",
                "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y",
            ]:
                try:
                    return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
        except Exception:
            pass
        return text

    def scrape_article(self, url: str, content_selector: str) -> str:
        logger.debug("Fetching article body: %s", url)
        html = self._fetch(url)
        if not html:
            return ""

        soup = BeautifulSoup(html, "lxml")

        if content_selector:
            content_el = soup.select_one(content_selector)
            if content_el:
                for tag in content_el.select("script, style, .advertisement, .related-posts, nav"):
                    tag.decompose()
                text = content_el.get_text(separator="\n", strip=True)
                text = re.sub(r"\n{3,}", "\n\n", text)
                return text[:8000]

        article = soup.find("article")
        if article:
            for tag in article.select("script, style, .advertisement, .related-posts, nav"):
                tag.decompose()
            return article.get_text(separator="\n", strip=True)[:8000]

        body = soup.find("body")
        if body:
            for tag in body.select("script, style, nav, header, footer, .advertisement, .sidebar"):
                tag.decompose()
            return body.get_text(separator="\n", strip=True)[:8000]

        return ""
