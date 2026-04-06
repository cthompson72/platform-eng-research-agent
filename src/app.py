import json
import os
import sys

import anthropic
import streamlit as st

# Allow imports from the src package when run via `streamlit run src/app.py`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.dedup import load_seen
from src.search import build_index, search_fts, rerank_with_claude

SYNTHESIZE_SYSTEM = """You are a research assistant for a Platform Engineering team at L'Oreal. Given a user question and a set of relevant articles, provide a clear, concise answer that synthesizes the information. Cite articles by number [1], [2], etc."""

SYNTHESIZE_USER = """Question: {query}

Relevant articles:
{articles_text}

Provide a synthesized answer to the question based on these articles. Use [N] citations to reference specific articles. If the articles don't fully answer the question, say what is covered and what gaps remain."""

SEEN_FILE = os.environ.get("SEEN_FILE", "data/seen_articles.json")


@st.cache_data(ttl=300)
def load_articles():
    return load_seen(SEEN_FILE)


def get_categories(seen: dict) -> list[str]:
    cats = sorted({m.get("category", "") for m in seen.values() if m.get("category")})
    return cats


def synthesize_answer(query: str, results: list[dict], api_key: str) -> str:
    if not results:
        return "No relevant articles found for this query."

    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"[{i}] {r.get('title', '')} ({r.get('first_seen', '')[:10]})\n"
            f"    {r.get('summary', 'No summary')}"
        )
    articles_text = "\n\n".join(lines)
    prompt = SYNTHESIZE_USER.format(query=query, articles_text=articles_text)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=SYNTHESIZE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def main():
    st.set_page_config(
        page_title="Platform Eng Research",
        page_icon=":mag:",
        layout="wide",
    )
    st.title("Platform Engineering Research Agent")
    st.caption("Semantic search over your article history — FTS5 + Claude re-ranking")

    # --- API key ---
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        api_key = st.sidebar.text_input("Anthropic API Key", type="password")
    if not api_key:
        st.info("Set ANTHROPIC_API_KEY in your environment or enter it in the sidebar.")
        return

    # --- Load data ---
    seen = load_articles()
    if not seen:
        st.error(f"No articles found in {SEEN_FILE}.")
        return

    # --- Sidebar filters ---
    st.sidebar.header("Filters")
    categories = get_categories(seen)
    selected_cat = st.sidebar.selectbox("Category", ["All"] + categories)
    category = None if selected_cat == "All" else selected_cat

    date_range = st.sidebar.slider("Last N days", min_value=7, max_value=180, value=180, step=7)
    min_score = st.sidebar.slider("Minimum score", min_value=1, max_value=10, value=1)

    st.sidebar.markdown("---")
    st.sidebar.metric("Articles in history", len(seen))

    # --- Pre-filter for display ---
    from src.query import _pre_filter
    filtered = _pre_filter(seen, date_range=date_range, category=category, min_score=min_score)
    st.sidebar.metric("After filters", len(filtered))

    # --- Search ---
    query = st.text_input("Search your research history", placeholder="e.g. kubernetes security best practices")

    if query:
        with st.spinner("Searching..."):
            conn = build_index(filtered)
            candidates = search_fts(conn, query, limit=50)
            conn.close()

        if not candidates:
            st.warning("No keyword matches found. Try different terms.")
            return

        with st.spinner("Re-ranking with Claude..."):
            results = rerank_with_claude(candidates, query, api_key, top_k=10)

        if not results:
            st.warning("No relevant results after re-ranking.")
            return

        # --- Synthesized answer ---
        with st.spinner("Synthesizing answer..."):
            answer = synthesize_answer(query, results, api_key)

        st.markdown("### Answer")
        st.markdown(answer)

        # --- Source articles ---
        st.markdown("---")
        st.markdown(f"### Sources ({len(results)} articles)")

        for i, r in enumerate(results, 1):
            score = r.get("score", "?")
            date = r.get("first_seen", "")[:10]
            tags = ", ".join(r.get("tags", []))
            relevance = r.get("relevance", "")
            url = r.get("url", "")

            with st.expander(f"[{i}] {r.get('title', '')}  —  {score}/10  |  {date}"):
                st.markdown(f"**Relevance:** {relevance}")
                if tags:
                    st.markdown(f"**Tags:** {tags}")
                st.markdown(f"**Summary:** {r.get('summary', 'No summary')}")
                st.markdown(f"[Read article]({url})")


if __name__ == "__main__":
    main()
