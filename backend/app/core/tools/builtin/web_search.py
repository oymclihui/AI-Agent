from langchain_core.tools import tool

from app.core.chat.web_context import search_web


@tool
async def web_search(query: str) -> str:
    """
    Searches the web for information about a given query.
    Returns a summary of the top search results.
    Use this to find current events, facts, or any information you don't know.
    """
    try:
        results = await search_web(query, max_results=5)
        if not results:
            return f"No direct results found for: {query}. Consider refining the query."
        lines = []
        for i, row in enumerate(results, 1):
            title = row.get("title") or f"Result {i}"
            url = row.get("url") or ""
            snippet = row.get("snippet") or ""
            part = f"{i}. {title}"
            if url:
                part += f" ({url})"
            if snippet:
                part += f"\n{snippet}"
            lines.append(part)
        return "\n\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"


WebSearchTool = web_search
