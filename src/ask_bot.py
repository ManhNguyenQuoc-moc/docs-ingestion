import os
import re
import sys
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

STORE_NAME = os.getenv("FILE_SEARCH_STORE_NAME")

SYSTEM_PROMPT = """
You are OptiBot, the customer-support bot for OptiSigns.com.

Tone:
- Helpful, factual, concise.
- Use simple step-by-step instructions when explaining how to do something.

Knowledge rules:
- Only answer using the uploaded documentation.
- If the uploaded documentation does not contain enough information, say:
  "I don't have enough information in the uploaded documentation to answer this."
- Do not guess, invent steps, or use outside knowledge.
- Do not mention internal details such as vector stores, chunks, embeddings, retrieval metadata, or file search.

Answer format:
- Use a maximum of 5 bullet points.
- If the answer needs more than 5 bullet points, give a short summary and suggest checking the source article.
- Prefer practical instructions over long explanations.
- Keep the answer focused on the user's question.

Citations:
- Cite up to 3 source articles per reply.
- When available, cite the exact "Article URL:" lines from the uploaded documents.
- If no source URL is available, cite the source article title instead.
"""


def get_grounding_metadata(response):
    if not response.candidates:
        return None

    candidate = response.candidates[0]

    if not getattr(candidate, "grounding_metadata", None):
        return None

    return candidate.grounding_metadata


def extract_article_url(text: str):
    if not text:
        return None

    match = re.search(r"Article URL:\s*(https?://\S+)", text)

    if match:
        return match.group(1).strip()

    return None


def get_sources(response, max_sources=3):
    grounding_metadata = get_grounding_metadata(response)

    if not grounding_metadata or not grounding_metadata.grounding_chunks:
        return []

    sources = []
    seen = set()

    for chunk in grounding_metadata.grounding_chunks:
        retrieved_context = getattr(chunk, "retrieved_context", None)

        if not retrieved_context:
            continue

        title = getattr(retrieved_context, "title", None)
        text = getattr(retrieved_context, "text", None)

        article_url = extract_article_url(text)

        source_key = article_url or title

        if not source_key or source_key in seen:
            continue

        seen.add(source_key)

        sources.append(
            {
                "title": title,
                "article_url": article_url,
            }
        )

        if len(sources) >= max_sources:
            break

    return sources


def print_sources(response):
    sources = get_sources(response)

    print("\nSources:")

    if not sources:
        print("- No source metadata found.")
        return

    for index, source in enumerate(sources, start=1):
        title = source.get("title")
        article_url = source.get("article_url")

        if title:
            print(f"{index}. {title}")

        if article_url:
            print(f"   Article URL: {article_url}")
        elif title:
            print(f"   Source article: {title}")


def print_grounded_segments(response, max_segments=5):
    grounding_metadata = get_grounding_metadata(response)

    if not grounding_metadata or not grounding_metadata.grounding_supports:
        return

    print("\nGrounded answer segments:")

    count = 0
    seen_segments = set()

    for support in grounding_metadata.grounding_supports:
        segment = getattr(support, "segment", None)

        if not segment:
            continue

        text = getattr(segment, "text", None)

        if not text:
            continue

        clean_text = " ".join(text.split())

        if clean_text in seen_segments:
            continue

        seen_segments.add(clean_text)

        if len(clean_text) > 180:
            clean_text = clean_text[:180] + "..."

        count += 1
        print(f"- {clean_text}")

        if count >= max_segments:
            break

    if count == 0:
        print("- No grounded segments found.")


def ask(question: str):
    if not STORE_NAME:
        raise ValueError("Missing FILE_SEARCH_STORE_NAME in .env")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=question,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[
                types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[STORE_NAME]
                    )
                )
            ],
            temperature=0.2,
        ),
    )

    print("=" * 80)
    print("Question")
    print("=" * 80)
    print(question)

    print("\n" + "=" * 80)
    print("Answer")
    print("=" * 80)

    answer = response.text.strip() if response.text else "No answer returned."
    print(answer)

    print_sources(response)
    print_grounded_segments(response)

    print("\n" + "=" * 80)
    print("Done")
    print("=" * 80)


def main():
    question = " ".join(sys.argv[1:]).strip()

    if not question:
        question = "How do I add a YouTube video?"

    ask(question)


if __name__ == "__main__":
    main()