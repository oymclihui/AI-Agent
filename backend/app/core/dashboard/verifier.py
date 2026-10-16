"""看板渲染验证：结构校验（必做）+ 无头浏览器渲染校验（playwright）。

蓝图 P0 验收：图表全渲染、控制台零报错、表格行数 > 0，通过才置 done。
playwright/chromium 不可用属环境故障 —— 显式抛错，任务置 failed，绝不静默跳过。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger("dashboard.verifier")

CHART_IDS = ["chart-daily", "chart-fl1", "chart-fl1-rate", "chart-fl2", "chart-neg", "chart-zk", "chart-dow"]


class DashboardVerifyError(Exception):
    """渲染验证失败（明细写入 verify_report）。"""


def structural_check(html: str) -> dict[str, Any]:
    """结构校验：区块齐全、自包含、数据快照可解析且非空、表格有行。"""
    report: dict[str, Any] = {"checks": []}

    def ck(name: str, ok: bool, detail: str = "") -> None:
        report["checks"].append({"name": name, "ok": bool(ok), "detail": detail})

    for cid in CHART_IDS:
        ck(f"chart_container:{cid}", f'id="{cid}"' in html)
    ck("self_contained:no_external_script", "<script src" not in html)
    ck("self_contained:no_external_link", "<link" not in html)
    ck("echarts:inlined", "echarts.init" in html and len(html) > 800_000)

    m = re.search(r"var DASH = (\{.*?\});\n", html, re.S)
    dash_ok = False
    row_stats: dict[str, int] = {}
    if m:
        try:
            dash = json.loads(m.group(1))
            row_stats = {k: len(v) for k, v in dash.items() if isinstance(v, list)}
            dash_ok = row_stats.get("daily", 0) > 0 and row_stats.get("fl1", 0) > 0
        except Exception as exc:
            ck("snapshot:parse", False, str(exc)[:200])
    ck("snapshot:daily_fl1_nonempty", dash_ok, json.dumps(row_stats))

    body_rows = len(re.findall(r"<tbody>.*?</tbody>", html, re.S))
    tr_count = len(re.findall(r"<tr>", html))
    ck("tables:row_count", tr_count >= 20, f"tbody={body_rows} tr={tr_count}")
    ck("no_template_leak", "__MARK_POINTS__" not in html and "{%" not in html)

    report["ok"] = all(c["ok"] for c in report["checks"])
    return report


async def browser_check(html: str, timeout_s: int = 60) -> dict[str, Any]:
    """无头 Chromium：SVG 图表数、控制台/页面错误、表格行数。"""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise DashboardVerifyError(f"playwright 未安装，无法执行无头浏览器验证：{exc}") from exc

    report: dict[str, Any] = {"console_errors": [], "page_errors": []}
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(args=["--no-sandbox"])
        except Exception as exc:
            raise DashboardVerifyError(f"chromium 启动失败：{str(exc)[:300]}") from exc
        try:
            page = await browser.new_page(viewport={"width": 1400, "height": 1000})
            page.on("console", lambda msg: report["console_errors"].append(msg.text[:300]) if msg.type == "error" else None)
            page.on("pageerror", lambda err: report["page_errors"].append(str(err)[:300]))
            await page.set_content(html, wait_until="load", timeout=timeout_s * 1000)
            await page.wait_for_timeout(1500)
            svg_count = await page.evaluate(
                "document.querySelectorAll('div[id^=\"chart-\"] svg').length"
            )
            tr_count = await page.evaluate("document.querySelectorAll('tbody tr').length")
            report["svg_count"] = svg_count
            report["table_rows"] = tr_count
            report["ok"] = (
                svg_count >= len(CHART_IDS)
                and tr_count > 0
                and not report["console_errors"]
                and not report["page_errors"]
            )
        finally:
            await browser.close()
    if not report.get("ok"):
        raise DashboardVerifyError(
            f"无头浏览器校验未过：svg={report.get('svg_count')}/{len(CHART_IDS)} "
            f"rows={report.get('table_rows')} console={report['console_errors'][:3]} page={report['page_errors'][:3]}"
        )
    return report


async def verify_dashboard(html: str) -> dict[str, Any]:
    """两级验证：结构 → 浏览器。任一失败抛 DashboardVerifyError。"""
    struct = await asyncio.to_thread(structural_check, html)
    if not struct["ok"]:
        failed = [c for c in struct["checks"] if not c["ok"]]
        raise DashboardVerifyError(f"结构校验未过：{[f['name'] for f in failed]}")
    browser = await browser_check(html)
    return {"ok": True, "structural": struct, "browser": browser}
