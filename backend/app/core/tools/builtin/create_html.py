import json
import re

from langchain_core.tools import tool

from app.core.artifacts import save_html_artifact

_VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1" />'


def _with_viewport(text: str) -> str:
    if "viewport" in text.lower():
        return text
    match = re.search(r"<head[^>]*>", text, flags=re.I)
    if not match:
        return text
    index = match.end()
    return text[:index] + "\n" + _VIEWPORT + text[index:]


def _document(html: str, title: str) -> str:
    text = (html or "").strip()
    if not text:
        raise ValueError("HTML 为空")
    if len(text) > 1_500_000:
        raise ValueError("HTML 超过 1.5MB")
    if "<html" in text.lower():
        return _with_viewport(text)
    safe_title = (title or "可视化页面").replace("<", "").replace(">", "")[:80]
    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"zh-CN\">\n"
        "<head>\n"
        "<meta charset=\"utf-8\" />\n"
        f"<title>{safe_title}</title>\n"
        f"{_VIEWPORT}\n"
        "</head>\n"
        f"<body>\n{text}\n</body>\n"
        "</html>\n"
    )


@tool
def create_html(html: str, filename: str = "visual.html", title: str = "可视化页面") -> str:
    """把可视化 HTML 存成可预览、可下载的单文件。

    用户要原型、信息图、幻灯片页面或任何可视化 HTML 时必须调用本工具。
    html: 一个能断网双击打开的单文件。CSS 和 JS 必须内联，不要引用外部 CDN、字体或图片链接。
    filename: 以 .html 结尾的英文文件名，例如 store-weekly.html。每次调用都会换成新链接，旧链接保持有效。
    回复里只写一两句说明，并原样放上 preview_url。右侧结果区会打开预览。不要把 HTML 源码贴进对话。
    """
    try:
        saved = save_html_artifact(_document(html, title), filename)
        payload = {
            "ok": True,
            **saved,
            "message": (
                "页面已生成。回复一两句即可，并原样放上 preview_url。"
                "右侧结果区会打开预览。不要粘贴 HTML 源码。"
                f" preview_url={saved['preview_url']}"
            ),
        }
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


CreateHtmlTool = create_html
