from langchain_core.tools import tool
import json


@tool
async def http_request(
    url: str,
    method: str = "GET",
    headers: str = "{}",
    body: str = "",
) -> str:
    """
    Makes an HTTP request to a given URL.
    Args:
        url: The URL to request.
        method: HTTP method (GET, POST, PUT, DELETE). Default: GET.
        headers: JSON string of headers. Default: empty.
        body: Request body as string. Default: empty.
    Returns the response body as a string (truncated to 2000 chars).
    """
    import httpx

    try:
        parsed_headers = json.loads(headers) if headers else {}
    except json.JSONDecodeError:
        parsed_headers = {}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=parsed_headers,
                content=body.encode() if body else None,
            )
        return response.text[:2000]
    except Exception as e:
        return f"HTTP request failed: {e}"


HttpRequestTool = http_request
