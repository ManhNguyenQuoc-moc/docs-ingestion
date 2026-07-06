import os
import re
from pathlib import Path

MARKDOWN_DIR = Path("data/markdown")

BAD_PATTERNS = [
    "submit a request",
    "sign in",
    "powered by zendesk",
    "related articles",
    "recently viewed articles",
    "was this article helpful",
]

MIN_FILE_SIZE = 500


def check_file(path: Path) -> dict:
    content = path.read_text(encoding="utf-8", errors="ignore")
    lower_content = content.lower()

    issues = []

    if not content.startswith("# "):
        issues.append("missing_h1_title")

    if "Article URL:" not in content:
        issues.append("missing_article_url")

    if len(content.encode("utf-8")) < MIN_FILE_SIZE:
        issues.append("too_short")

    if "<script" in lower_content or "<style" in lower_content:
        issues.append("contains_script_or_style")

    if re.search(r"<nav|<footer|<header|<aside", lower_content):
        issues.append("contains_layout_html")

    bad_matches = [pattern for pattern in BAD_PATTERNS if pattern in lower_content]
    if bad_matches:
        issues.append(f"possible_noise: {', '.join(bad_matches)}")

    markdown_links = re.findall(r"\[[^\]]+\]\([^)]+\)", content)
    raw_html_tags = re.findall(r"<[a-zA-Z][^>]*>", content)

    return {
        "file": str(path),
        "size": len(content.encode("utf-8")),
        "links": len(markdown_links),
        "html_tags": len(raw_html_tags),
        "issues": issues,
    }


def main():
    files = sorted(MARKDOWN_DIR.glob("*.md"))

    if not files:
        print("[ERROR] No markdown files found in data/markdown")
        return

    print(f"[INFO] Found {len(files)} markdown files")

    failed = []

    for file in files:
        result = check_file(file)

        if result["issues"]:
            failed.append(result)
            print(f"[WARN] {result['file']}")
            print(f"       issues: {result['issues']}")
            print(f"       size: {result['size']} bytes")
            print(f"       links: {result['links']}, html_tags: {result['html_tags']}")

    print("\n========== SUMMARY ==========")
    print(f"Total files: {len(files)}")
    print(f"Files with issues: {len(failed)}")
    print(f"Passed files: {len(files) - len(failed)}")

    if len(files) < 30:
        print("[FAIL] Less than 30 markdown files")
    else:
        print("[PASS] File count requirement satisfied")

    if failed:
        print("[CHECK] Open warning files manually and inspect content")
    else:
        print("[PASS] No obvious markdown quality issues found")


if __name__ == "__main__":
    main()