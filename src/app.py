import contextlib
import io
import os
import re
from dotenv import load_dotenv
import streamlit as st
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
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


def extract_article_url(text: str):
    if not text:
        return None

    match = re.search(r"Article URL:\s*(https?://\S+)", text)

    if match:
        return match.group(1).strip()

    return None


def get_grounding_metadata(response):
    if not response.candidates:
        return None

    candidate = response.candidates[0]

    if not getattr(candidate, "grounding_metadata", None):
        return None

    return candidate.grounding_metadata


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


def ask_optibot(question: str):
    if not GEMINI_API_KEY:
        raise ValueError("Missing GEMINI_API_KEY in .env")

    if not STORE_NAME:
        raise ValueError("Missing FILE_SEARCH_STORE_NAME in .env")

    client = genai.Client(api_key=GEMINI_API_KEY)

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

    answer = response.text.strip() if response.text else "No answer returned."
    sources = get_sources(response)

    return answer, sources


st.set_page_config(
    page_title="Docs Assistant",
    page_icon="DOC",
    layout="centered",
)

st.title("Docs Assistant")
st.caption("Documentation ingestion and support assistant")

with st.sidebar:
    st.header("Status")

    if GEMINI_API_KEY:
        st.success("GEMINI_API_KEY loaded")
    else:
        st.error("Missing GEMINI_API_KEY")

    if STORE_NAME:
        st.success("FILE_SEARCH_STORE_NAME loaded")
        st.code(STORE_NAME)
    else:
        st.error("Missing FILE_SEARCH_STORE_NAME")

    st.divider()
    st.write("Sample questions:")
    st.code("How do I add a YouTube video?")
    st.code("How do I pre-configure Wi-Fi?")
    st.code("How do I use the Data Studio app?")

ask_tab, ingestion_tab = st.tabs(["Ask", "Ingestion"])

with ingestion_tab:
    st.subheader("Daily ingestion job")
    st.write("Run the same pipeline as `python src/main.py`.")

    if st.button("Run ingestion now", type="primary"):
        log_buffer = io.StringIO()

        with st.spinner("Scraping, processing, and uploading changed files..."):
            try:
                from main import main as run_ingestion

                with contextlib.redirect_stdout(log_buffer), contextlib.redirect_stderr(log_buffer):
                    summary = run_ingestion()

                st.success("Ingestion completed")

                col1, col2, col3 = st.columns(3)
                col1.metric("Markdown files", summary["local_markdown_files"])
                col2.metric("Changed/new", summary["changed_or_new_files"])
                col3.metric("Uploaded", summary["upload_success"])

                st.json(summary)

            except Exception as error:
                st.error(f"Ingestion failed: {error}")

        st.text_area(
            "CLI output",
            log_buffer.getvalue(),
            height=360,
        )

    st.divider()
    st.code("python src/main.py", language="bash")

with ask_tab:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    question = st.chat_input("Ask a support question...")

    if not st.session_state.messages:
        st.info("Try asking: How do I add a YouTube video?")

    if question:
        st.session_state.messages.append(
            {
                "role": "user",
                "content": question,
            }
        )

        with st.spinner("Searching uploaded documentation..."):
            try:
                answer, sources = ask_optibot(question)

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": answer,
                        "sources": sources,
                    }
                )

            except Exception as error:
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": f"Error: {error}",
                        "sources": [],
                    }
                )

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            sources = message.get("sources", [])

            if sources:
                with st.expander("Sources"):
                    for index, source in enumerate(sources, start=1):
                        title = source.get("title") or "Untitled source"
                        article_url = source.get("article_url")

                        st.markdown(f"**{index}. {title}**")

                        if article_url:
                            st.markdown(f"Article URL: {article_url}")
                        else:
                            st.markdown("Article URL: Not found in retrieved chunk")
