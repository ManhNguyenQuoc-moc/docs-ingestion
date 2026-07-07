import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

ROOT_DIR = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT_DIR / "data" / "markdown"
STATE_FILE = ROOT_DIR / "state.json"
LOG_DIR = ROOT_DIR / "logs"
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


def file_hash(file_path: Path) -> str:
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(state: dict):
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def wait_for_operation(operation):
    while not operation.done:
        print("Indexing... waiting 5 seconds")
        time.sleep(5)
        operation = client.operations.get(operation)
    return operation


def normalize_state_entry(entry):
    """
    Backward compatibility:
    Old state format:
      "file.md": "hash"

    New state format:
      "file.md": {
        "hash": "...",
        "document_name": "fileSearchStores/.../documents/..."
      }
    """
    if isinstance(entry, str):
        return {
            "hash": entry,
            "document_name": None,
        }

    if isinstance(entry, dict):
        return {
            "hash": entry.get("hash"),
            "document_name": entry.get("document_name"),
        }

    return {
        "hash": None,
        "document_name": None,
    }


def get_document_display_name(document):
    for attr in ["display_name", "displayName", "title"]:
        value = getattr(document, attr, None)
        if value:
            return value

    return None


def list_store_documents_by_display_name():
    print("Listing existing documents from File Search Store...")

    documents = client.file_search_stores.documents.list(parent=STORE_NAME)
    document_map = {}

    for document in documents:
        document_name = getattr(document, "name", None)
        display_name = get_document_display_name(document)

        if document_name and display_name:
            document_map[display_name] = document_name

    print(f"Found existing store documents: {len(document_map)}")
    return document_map


def bootstrap_state_from_store(markdown_files, old_state):
    """
    If state.json is missing in a fresh container, infer document names from the
    remote store by display_name. This prevents re-uploading every file.
    """
    missing_files = []

    for file_path in markdown_files:
        old_entry = normalize_state_entry(old_state.get(file_path.name))

        if not old_entry.get("hash") or not old_entry.get("document_name"):
            missing_files.append(file_path)

    if not missing_files:
        return dict(old_state), 0

    document_map = list_store_documents_by_display_name()
    bootstrapped_state = dict(old_state)
    bootstrapped_count = 0

    for file_path in missing_files:
        document_name = document_map.get(file_path.name)

        if not document_name:
            continue

        bootstrapped_state[file_path.name] = {
            "hash": file_hash(file_path),
            "document_name": document_name,
            "updated_at": datetime.now().isoformat(),
            "state_source": "bootstrapped_from_store",
        }
        bootstrapped_count += 1

    if bootstrapped_count:
        print(f"Bootstrapped state entries from store: {bootstrapped_count}")

    return bootstrapped_state, bootstrapped_count


def extract_document_name(operation):
    """
    Try to extract the created document name from the upload operation.

    Different google-genai versions may expose the final document differently,
    so this function checks several common places.
    """
    # 1. operation.response.name
    response = getattr(operation, "response", None)
    if response:
        name = getattr(response, "name", None)
        if name and "/documents/" in name:
            return name

        document = getattr(response, "document", None)
        if document:
            name = getattr(document, "name", None)
            if name and "/documents/" in name:
                return name

    # 2. operation.metadata.document.name
    metadata = getattr(operation, "metadata", None)
    if metadata:
        document = getattr(metadata, "document", None)
        if document:
            name = getattr(document, "name", None)
            if name and "/documents/" in name:
                return name

        name = getattr(metadata, "document_name", None)
        if name and "/documents/" in name:
            return name

    # 3. fallback: parse string representation
    operation_text = str(operation)
    marker = "fileSearchStores/"
    start = operation_text.find(marker)

    while start != -1:
        end = operation_text.find("'", start)
        if end == -1:
            end = operation_text.find('"', start)
        if end == -1:
            end = operation_text.find(" ", start)
        if end == -1:
            end = len(operation_text)

        possible_name = operation_text[start:end].strip("',\")\n ")
        if "/documents/" in possible_name:
            return possible_name

        start = operation_text.find(marker, start + 1)

    return None


def delete_document(document_name: str):
    if not document_name:
        return False

    print(f"Deleting old document: {document_name}")

    try:
        client.file_search_stores.documents.delete(
            name=document_name,
            config={
                "force": True,
            },
        )
        print("Old document deleted.")
        return True

    except TypeError:
        try:
            client.file_search_stores.documents.delete(
                name=document_name,
                force=True,
            )
            print("Old document deleted.")
            return True

        except TypeError:
            try:
                client.file_search_stores.documents.delete(
                    name=document_name
                )
                print("Old document deleted.")
                return True

            except Exception as e:
                print(f"Warning: could not delete old document: {document_name}")
                print(e)
                return False

        except Exception as e:
            print(f"Warning: could not delete old document: {document_name}")
            print(e)
            return False

    except Exception as e:
        print(f"Warning: could not delete old document: {document_name}")
        print(e)
        return False


def upload_file(file_path: Path):
    print(f"Uploading changed/new file: {file_path.name}")

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

    completed_operation = wait_for_operation(operation)
    document_name = extract_document_name(completed_operation)

    if not document_name:
        print("Warning: Could not extract document_name from upload operation.")
        print("The upload may still be successful, but update/delete tracking will be limited.")

    return document_name


def write_log(summary: dict):
    LOG_DIR.mkdir(exist_ok=True)

    log_file = LOG_DIR / f"ingestion-{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.json"

    log_file.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return log_file


def run_scraper():
    """
    Run the full local ingestion pipeline before uploading changes:
    Zendesk API -> raw JSON -> cleaned Markdown.
    """
    from processor import process_articles
    from scraper import scrape_articles

    print("Running scraper...")
    articles = scrape_articles()

    print("Converting scraped articles to Markdown...")
    processing_summary = process_articles()

    print(
        "Scraper summary: "
        f"scraped={len(articles)}, "
        f"added={processing_summary['added']}, "
        f"updated={processing_summary['updated']}, "
        f"skipped={processing_summary['skipped']}"
    )

    return {
        "scraped_articles": len(articles),
        "processed_total": processing_summary["total"],
        "processor_added": processing_summary["added"],
        "processor_updated": processing_summary["updated"],
        "processor_skipped": processing_summary["skipped"],
    }


def main():
    if not STORE_NAME:
        raise ValueError("Missing FILE_SEARCH_STORE_NAME in .env")

    scraper_summary = run_scraper()

    print(f"Root dir: {ROOT_DIR}")
    print(f"Docs dir: {DOCS_DIR}")
    print(f"Docs dir exists: {DOCS_DIR.exists()}")

    if not DOCS_DIR.exists():
        raise FileNotFoundError(f"Docs folder not found: {DOCS_DIR}")

    markdown_files = sorted(DOCS_DIR.glob("*.md"))
    print(f"Found Markdown files: {len(markdown_files)}")

    old_state = load_state()
    old_state, bootstrapped_state_entries = bootstrap_state_from_store(
        markdown_files,
        old_state,
    )
    new_state = dict(old_state)

    changed_files = []
    skipped_files = []

    for file_path in markdown_files:
        current_hash = file_hash(file_path)
        old_entry = normalize_state_entry(old_state.get(file_path.name))

        if old_entry.get("hash") != current_hash:
            changed_files.append(
                {
                    "path": file_path,
                    "hash": current_hash,
                    "old_document_name": old_entry.get("document_name"),
                }
            )
        else:
            skipped_files.append(file_path)

    success = 0
    failed = 0
    deleted_old_documents = 0
    failed_files = []

    for item in changed_files:
        file_path = item["path"]
        current_hash = item["hash"]
        old_document_name = item["old_document_name"]

        try:
            new_document_name = upload_file(file_path)

            if not new_document_name:
                raise RuntimeError(
                    f"Upload succeeded but could not extract document_name for {file_path.name}"
                )

            if old_document_name and old_document_name != new_document_name:
                deleted = delete_document(old_document_name)
                if deleted:
                    deleted_old_documents += 1

            new_state[file_path.name] = {
                "hash": current_hash,
                "document_name": new_document_name,
                "updated_at": datetime.now().isoformat(),
            }

            success += 1
            print(f"Uploaded successfully: {file_path.name}")

        except Exception as e:
            failed += 1
            failed_files.append(
                {
                    "file": file_path.name,
                    "error": str(e),
                }
            )
            print(f"Failed to upload: {file_path.name}")
            print(e)

    save_state(new_state)

    store = client.file_search_stores.get(name=STORE_NAME)

    summary = {
        "timestamp": datetime.now().isoformat(),
        **scraper_summary,
        "bootstrapped_state_entries": bootstrapped_state_entries,
        "local_markdown_files": len(markdown_files),
        "changed_or_new_files": len(changed_files),
        "skipped_unchanged_files": len(skipped_files),
        "deleted_old_documents": deleted_old_documents,
        "upload_success": success,
        "upload_failed": failed,
        "failed_files": failed_files,
        "active_documents": store.active_documents_count,
        "pending_documents": store.pending_documents_count,
        "failed_documents": store.failed_documents_count,
        "store_size_bytes": store.size_bytes,
    }

    log_file = write_log(summary)

    print("\nDaily ingestion summary")
    for key, value in summary.items():
        print(f"{key}: {value}")

    print(f"log_file: {log_file}")
    print("INGESTION_SUMMARY_JSON=" + json.dumps(summary, ensure_ascii=False))

    return summary


if __name__ == "__main__":
    main()
