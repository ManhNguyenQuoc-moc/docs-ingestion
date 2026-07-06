import os
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

ROOT_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT_DIR / "data" / "markdown"
STORE_NAME = os.getenv("FILE_SEARCH_STORE_NAME")


def get_mime_type(file_path: Path) -> str:
    suffix = file_path.suffix.lower()

    if suffix == ".md":
        return "text/plain"
    if suffix == ".txt":
        return "text/plain"
    if suffix == ".html":
        return "text/html"
    if suffix == ".pdf":
        return "application/pdf"

    raise ValueError(f"Unsupported file type: {suffix}")


def wait_for_operation(operation):
    while not operation.done:
        print("Indexing... waiting 5 seconds")
        time.sleep(5)
        operation = client.operations.get(operation)
    return operation


def upload_file(file_path: Path):
    print(f"Uploading: {file_path.name}")

    operation = client.file_search_stores.upload_to_file_search_store(
        file=str(file_path),
        file_search_store_name=STORE_NAME,
        config={
            "display_name": file_path.name,
            "mime_type": get_mime_type(file_path),
            "chunking_config": {
                "white_space_config": {
                    "max_tokens_per_chunk": 300,
                    "max_overlap_tokens": 50,
                }
            },
        },
    )

    wait_for_operation(operation)
    print(f"Done: {file_path.name}")


def main():
    if not STORE_NAME:
        raise ValueError("Missing FILE_SEARCH_STORE_NAME in .env")

    if not DOCS_DIR.exists():
        raise FileNotFoundError(f"Docs folder not found: {DOCS_DIR}")

    markdown_files = sorted(DOCS_DIR.glob("*.md"))

    if not markdown_files:
        print("No Markdown files found in docs/")
        return

    success = 0
    failed = 0

    for file_path in markdown_files:
        try:
            upload_file(file_path)
            success += 1
        except Exception as e:
            failed += 1
            print(f"Failed: {file_path.name}")
            print(e)

    store = client.file_search_stores.get(name=STORE_NAME)

    print("\nUpload summary")
    print(f"Local Markdown files: {len(markdown_files)}")
    print(f"Upload success: {success}")
    print(f"Upload failed: {failed}")
    print(f"Active documents: {store.active_documents_count}")
    print(f"Pending documents: {store.pending_documents_count}")
    print(f"Failed documents: {store.failed_documents_count}")
    print(f"Store size bytes: {store.size_bytes}")


if __name__ == "__main__":
    main()