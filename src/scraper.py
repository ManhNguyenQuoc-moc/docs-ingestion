import json
import os
import time
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "https://support.optisigns.com").rstrip("/")
LOCALE = os.getenv("LOCALE", "en-us")
MAX_ARTICLES = int(os.getenv("MAX_ARTICLES", "30"))

RAW_DIR = "data/raw"
RAW_OUTPUT_FILE = os.path.join(RAW_DIR, "articles.json")


def get_articles_api_url() -> str:
    """
    API lấy danh sách articles từ Zendesk Help Center.

    Ví dụ:
    https://support.optisigns.com/api/v2/help_center/en-us/articles.json
    """
    return f"{BASE_URL}/api/v2/help_center/{LOCALE}/articles.json"


def fetch_json(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Gửi request GET đến Zendesk API và trả về JSON.
    """
    response = requests.get(
        url,
        params=params,
        timeout=30,
        headers={
            "User-Agent": "knowledge-sync/1.0"
        },
    )

    response.raise_for_status()
    return response.json()


def normalize_article(article: Dict[str, Any]) -> Dict[str, Any]:
    """
    Giữ lại những field cần cho bước xử lý Markdown và detect update sau này.

    Không clean HTML ở đây.
    Không convert Markdown ở đây.
    """
    return {
        "id": article.get("id"),
        "title": article.get("title"),
        "url": article.get("html_url"),
        "api_url": article.get("url"),
        "body_html": article.get("body"),
        "locale": article.get("locale"),
        "section_id": article.get("section_id"),
        "created_at": article.get("created_at"),
        "updated_at": article.get("updated_at"),
        "edited_at": article.get("edited_at"),
    }


def reached_limit(articles: List[Dict[str, Any]]) -> bool:
    """
    MAX_ARTICLES = 0 nghĩa là lấy tất cả.
    MAX_ARTICLES > 0 nghĩa là dừng khi đủ số lượng.
    """
    return MAX_ARTICLES > 0 and len(articles) >= MAX_ARTICLES


def scrape_articles() -> List[Dict[str, Any]]:
    """
    Lấy articles từ Zendesk Help Center API và lưu vào data/raw/articles.json.
    """
    os.makedirs(RAW_DIR, exist_ok=True)

    articles: List[Dict[str, Any]] = []

    next_page: Optional[str] = get_articles_api_url()

    params: Optional[Dict[str, Any]] = {
        "per_page": 100,
        "sort_by": "updated_at",
        "sort_order": "desc",
    }

    while next_page:
        print(f"[SCRAPER] Fetching: {next_page}")

        data = fetch_json(next_page, params=params)

        api_articles = data.get("articles", [])

        print(f"[SCRAPER] Found {len(api_articles)} articles in this page")

        for item in api_articles:
            if reached_limit(articles):
                break

            article = normalize_article(item)

            if not article["id"] or not article["title"] or not article["body_html"]:
                print("[SCRAPER] Skipped invalid article")
                continue

            articles.append(article)

            print(f"[SCRAPER] Collected {len(articles)}: {article['title']}")

        if reached_limit(articles):
            break

        next_page = data.get("next_page")

        # next_page đã có query string sẵn, nên page sau không truyền params nữa
        params = None

        time.sleep(0.3)

    with open(RAW_OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(articles, file, ensure_ascii=False, indent=2)

    print(f"[SCRAPER] Saved {len(articles)} articles to {RAW_OUTPUT_FILE}")

    return articles


if __name__ == "__main__":
    scrape_articles()