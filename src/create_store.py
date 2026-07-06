import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def main():
    store = client.file_search_stores.create(
        config={
            "display_name": "support-knowledge-store",
            "embedding_model": "models/gemini-embedding-2",
        }
    )

    print("File Search Store created:")
    print(store.name)
    print("\nCopy this value into .env:")
    print(f"FILE_SEARCH_STORE_NAME={store.name}")


if __name__ == "__main__":
    main()