import hashlib
import json
import os
import re
from typing import Any, Dict, List

from bs4 import BeautifulSoup
from markdownify import markdownify as to_markdown

RAW_INPUT_FILE = "data/raw/articles.json"
MARKDOWN_DIR = "data/markdown"
STATE_FILE = "data/articles_state.json"


def slugify(text: str) -> str:
    """
    Chuyển title thành tên file an toàn.
    Ví dụ:
    "How to Add YouTube Video?" -> "how-to-add-youtube-video"
    """
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")

    return text[:100] or "untitled"


def calculate_hash(content: str) -> str:
    """
    Tạo hash để phát hiện nội dung thay đổi.
    Sau này Step 3 sẽ dùng để biết bài nào cần upload lại.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_articles() -> List[Dict[str, Any]]:
    """
    Đọc dữ liệu raw từ scraper.
    """
    if not os.path.exists(RAW_INPUT_FILE):
        raise FileNotFoundError(
            f"Cannot find {RAW_INPUT_FILE}. Please run scraper.py first."
        )

    with open(RAW_INPUT_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def load_state() -> Dict[str, Any]:
    """
    Đọc trạng thái cũ để detect added / updated / skipped.
    """
    if not os.path.exists(STATE_FILE):
        return {}

    with open(STATE_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_state(state: Dict[str, Any]) -> None:
    """
    Lưu trạng thái mới.
    """
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def clean_html(html: str) -> str:
    """
    Làm sạch HTML trước khi convert Markdown.

    Vì dữ liệu lấy từ Zendesk API nên body_html thường đã là phần nội dung chính.
    Tuy nhiên vẫn nên loại bỏ script, style, iframe rác, button, form...
    """
    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "button"]):
        tag.decompose()

    # Xóa attribute không cần thiết để Markdown gọn hơn
    for tag in soup.find_all(True):
        allowed_attrs = {}

        if tag.name == "a" and tag.get("href"):
            allowed_attrs["href"] = tag.get("href")

        if tag.name == "img" and tag.get("src"):
            allowed_attrs["src"] = tag.get("src")
            if tag.get("alt"):
                allowed_attrs["alt"] = tag.get("alt")

        tag.attrs = allowed_attrs

    return str(soup)


def convert_article_to_markdown(article: Dict[str, Any]) -> str:
    """
    Convert một article sang Markdown hoàn chỉnh.
    """
    title = article.get("title", "Untitled Article")
    url = article.get("url", "")
    updated_at = article.get("updated_at", "")
    body_html = article.get("body_html", "")

    cleaned_html = clean_html(body_html)

    markdown_body = to_markdown(
        cleaned_html,
        heading_style="ATX",
        bullets="-",
        strip=["span"],
    )

    markdown_body = re.sub(r"\n{3,}", "\n\n", markdown_body).strip()

    return f"""# {title}

Article URL: {url}
Updated At: {updated_at}

---

{markdown_body}
"""


def process_articles() -> Dict[str, Any]:
    """
    Xử lý toàn bộ articles:
    - HTML -> Markdown
    - Lưu file .md
    - Detect added / updated / skipped bằng hash
    """
    os.makedirs(MARKDOWN_DIR, exist_ok=True)

    articles = load_articles()
    state = load_state()

    added = 0
    updated = 0
    skipped = 0
    changed_files = []
    results = []

    for article in articles:
        article_id = str(article.get("id"))
        title = article.get("title", "Untitled Article")

        if not article_id or not article.get("body_html"):
            print(f"[PROCESSOR] Skipped invalid article: {title}")
            continue

        markdown = convert_article_to_markdown(article)
        content_hash = calculate_hash(markdown)

        slug = slugify(title)
        filename = f"{slug}.md"
        filepath = os.path.join(MARKDOWN_DIR, filename)

        previous = state.get(article_id)

        if previous and previous.get("hash") == content_hash:
            status = "skipped"
            skipped += 1
        else:
            with open(filepath, "w", encoding="utf-8") as file:
                file.write(markdown)

            if previous:
                status = "updated"
                updated += 1
            else:
                status = "added"
                added += 1

            changed_files.append(filepath)

            state[article_id] = {
                "id": article.get("id"),
                "title": title,
                "url": article.get("url"),
                "file": filepath,
                "hash": content_hash,
                "updated_at": article.get("updated_at"),
            }

        results.append({
            "id": article.get("id"),
            "title": title,
            "file": filepath,
            "status": status,
        })

        print(f"[PROCESSOR] {status.upper()}: {title}")

    save_state(state)

    summary = {
        "total": len(results),
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "changed_files": changed_files,
        "results": results,
    }

    return summary


if __name__ == "__main__":
    result = process_articles()
    print(json.dumps(result, ensure_ascii=False, indent=2))