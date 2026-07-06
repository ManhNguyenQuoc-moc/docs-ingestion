import hashlib
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

ROOT_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT_DIR / "data" / "markdown"
STATE_FILE = ROOT_DIR / "state.json"
STORE_NAME = os.getenv("FILE_SEARCH_STORE_NAME")


def file_hash(file_path: Path) -> str:
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def get_document_display_name(document):
    for attr in ["display_name", "displayName", "title"]:
        value = getattr(document, attr, None)
        if value:
            return value

    return None


def main():
    if not STORE_NAME:
        raise ValueError("Missing FILE_SEARCH_STORE_NAME in .env")

    if not DOCS_DIR.exists():
        raise FileNotFoundError(f"Docs folder not found: {DOCS_DIR}")

    markdown_files = sorted(DOCS_DIR.glob("*.md"))

    print(f"Found local Markdown files: {len(markdown_files)}")

    print("Listing documents from File Search Store...")

    documents = client.file_search_stores.documents.list(
        parent=STORE_NAME
    )

    document_map = {}

    for document in documents:
        document_name = getattr(document, "name", None)
        display_name = get_document_display_name(document)

        if not document_name:
            continue

        if not display_name:
            continue

        # Nếu có duplicate cùng display_name, bản sau sẽ overwrite bản trước.
        # Mục tiêu là từ giờ về sau state có document_name để update/delete được.
        document_map[display_name] = document_name

        print(f"- {display_name}")
        print(f"  {document_name}")

    new_state = {}
    missing_documents = []

    for file_path in markdown_files:
        document_name = document_map.get(file_path.name)

        if not document_name:
            missing_documents.append(file_path.name)

        new_state[file_path.name] = {
            "hash": file_hash(file_path),
            "document_name": document_name,
        }

    STATE_FILE.write_text(
        json.dumps(new_state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nRebuild state summary")
    print(f"Local Markdown files: {len(markdown_files)}")
    print(f"Matched documents: {len(markdown_files) - len(missing_documents)}")
    print(f"Missing documents: {len(missing_documents)}")
    print(f"State file written to: {STATE_FILE}")

    if missing_documents:
        print("\nFiles without matching document in store:")
        for filename in missing_documents:
            print(f"- {filename}")


if __name__ == "__main__":
    main()