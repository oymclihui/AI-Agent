from langchain_core.tools import tool


@tool
async def web_search(query: str) -> str:
    """
    Searches the web for information about a given query.
    Returns a summary of the top search results.
    Use this to find current events, facts, or any information you don't know.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Using DuckDuckGo Instant Answer API (no API key required)
            response = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_redirect": "1", "no_html": "1"},
            )
            data = response.json()

        results = []
        if data.get("Abstract"):
            results.append(f"Summary: {data['Abstract']}")
        if data.get("Answer"):
            results.append(f"Answer: {data['Answer']}")
        for topic in data.get("RelatedTopics", [])[:3]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(f"- {topic['Text']}")

        if results:
            return "\n".join(results)
        return f"No direct results found for: {query}. Consider refining the query."

    except Exception as e:
        return f"Search failed: {e}"


WebSearchTool = web_search
