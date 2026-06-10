"""
Demo: 3 Excel sheets -> one wide table via AI-AGENT workflow.

Creates sample orders / customers / products workbooks, registers a Code-node
workflow, executes it through the workflow engine, and prints the merged result.

Usage:
    cd backend
    python -m pip install openpyxl   # once
    python scripts/demo_excel_wide_table.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "demo_data" / "excel_merge"
API = "http://127.0.0.1:8000/api/v1"

MERGE_CODE = r"""
data_dir = Path(input_data.get("data_dir", "."))
output_path = Path(input_data.get("output_path", data_dir / "wide_table.xlsx"))

orders = pd.read_excel(data_dir / "orders.xlsx")
customers = pd.read_excel(data_dir / "customers.xlsx")
products = pd.read_excel(data_dir / "products.xlsx")

wide = orders.merge(customers, on="customer_id", how="left")
wide = wide.merge(products, on="product_id", how="left")
wide["amount"] = wide["quantity"] * wide["unit_price"]

output_path.parent.mkdir(parents=True, exist_ok=True)
wide.to_excel(output_path, index=False)

result = {
    "rows": int(len(wide)),
    "columns": list(wide.columns),
    "output_path": str(output_path),
    "preview": wide.head(10).to_dict(orient="records"),
    "final_output": (
        f"宽表已生成：{len(wide)} 行 × {len(wide.columns)} 列，"
        f"输出文件 {output_path.name}"
    ),
}
"""


def create_sample_excels() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    orders = pd.DataFrame([
        {"order_id": "O001", "customer_id": "C001", "product_id": "P001", "quantity": 2, "order_date": "2026-06-01"},
        {"order_id": "O002", "customer_id": "C002", "product_id": "P002", "quantity": 1, "order_date": "2026-06-02"},
        {"order_id": "O003", "customer_id": "C001", "product_id": "P003", "quantity": 5, "order_date": "2026-06-03"},
        {"order_id": "O004", "customer_id": "C003", "product_id": "P001", "quantity": 3, "order_date": "2026-06-04"},
        {"order_id": "O005", "customer_id": "C002", "product_id": "P003", "quantity": 2, "order_date": "2026-06-05"},
    ])
    customers = pd.DataFrame([
        {"customer_id": "C001", "customer_name": "华东零售", "region": "华东"},
        {"customer_id": "C002", "customer_name": "华南连锁", "region": "华南"},
        {"customer_id": "C003", "customer_name": "华北商超", "region": "华北"},
    ])
    products = pd.DataFrame([
        {"product_id": "P001", "product_name": "智能手环", "category": "穿戴", "unit_price": 299.0},
        {"product_id": "P002", "product_name": "无线耳机", "category": "音频", "unit_price": 499.0},
        {"product_id": "P003", "product_name": "移动电源", "category": "配件", "unit_price": 129.0},
    ])

    orders.to_excel(DATA_DIR / "orders.xlsx", index=False)
    customers.to_excel(DATA_DIR / "customers.xlsx", index=False)
    products.to_excel(DATA_DIR / "products.xlsx", index=False)

    print(f"[1/4] 已生成 3 张 Excel -> {DATA_DIR}")
    print(f"      orders.xlsx ({len(orders)} 行), customers.xlsx ({len(customers)} 行), products.xlsx ({len(products)} 行)")
    return DATA_DIR


def build_workflow_graph() -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "开始", "config": {}, "position": {"x": 0, "y": 0}},
            {
                "id": "merge_wide",
                "type": "code",
                "catalog_id": "code",
                "label": "合并三张表为宽表",
                "config": {"code": MERGE_CODE},
                "position": {"x": 280, "y": 0},
            },
            {"id": "end", "type": "end", "label": "结束", "config": {}, "position": {"x": 560, "y": 0}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "merge_wide"},
            {"id": "e2", "source": "merge_wide", "target": "end"},
        ],
    }


async def execute_workflow_in_process(wf_id: str, input_data: dict) -> dict:
    sys.path.insert(0, str(ROOT))
    from app.core.tools.registry import ToolRegistry
    from app.core.workflow.engine import WorkflowBuilder, WorkflowEngine
    from app.db.models import Workflow
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        wf = await db.get(Workflow, wf_id)
        if not wf:
            raise RuntimeError(f"Workflow {wf_id} not found")
        graph = await WorkflowBuilder.build(wf, ToolRegistry.get_instance(), {})
        engine = WorkflowEngine(graph)
        state = await engine.execute(input_data)
        return {
            "status": "failed" if state.errors else "completed",
            "final_output": state.final_output,
            "errors": state.errors,
            "rows": state.context.get("rows"),
            "columns": state.context.get("columns"),
            "preview": state.context.get("preview"),
            "output_path": state.context.get("output_path"),
        }


def run_demo() -> int:
    api_ok = False
    try:
        httpx.get("http://127.0.0.1:8000/health", timeout=5.0)
        api_ok = True
    except Exception:
        print("WARN: 后端 API 未启动，将仅本地执行引擎（工作流仍会写入数据库需 API 或改脚本）")

    data_dir = create_sample_excels()
    output_path = data_dir / "wide_table.xlsx"
    if output_path.exists():
        output_path.unlink()

    graph = build_workflow_graph()
    wf_id = None

    if api_ok:
        payload = {
            "name": "Excel多表合并宽表（演示）",
            "description": "读取 orders / customers / products 三张 Excel，按 customer_id 与 product_id 关联生成宽表",
            "process_type": "sequential",
            "graph_definition": graph,
        }
        print("[2/4] 通过 API 创建工作流（Start -> Code 合并 -> End）...")
        with httpx.Client(base_url=API, timeout=120.0) as client:
            r = client.post("/workflows/", json=payload)
            r.raise_for_status()
            wf_id = r.json()["id"]
    else:
        print("[2/4] 跳过后端 API，请启动后端后在工作流页手动导入 graph_definition")
        return 1

    print(f"      workflow_id = {wf_id}")
    print(f"      UI: http://localhost:3000/workflows/{wf_id}")

    exec_input = {
        "input": "将三张 Excel 合并为一张大宽表",
        "data_dir": str(data_dir),
        "output_path": str(output_path),
    }
    print("[3/4] 执行工作流引擎...")
    result = asyncio.run(execute_workflow_in_process(wf_id, exec_input))

    print(f"[4/4] 执行完成 status={result['status']}")
    if result.get("errors"):
        print("错误:", result["errors"])
        return 1

    print(f"\n>>> {result.get('final_output')}")

    if output_path.is_file():
        wide = pd.read_excel(output_path)
        print(f"\n宽表文件: {output_path}")
        print(f"维度: {len(wide)} 行 × {len(wide.columns)} 列")
        print(f"列名: {', '.join(wide.columns.astype(str))}")
        print("\n预览（全部 {0} 行）:".format(len(wide)))
        print(wide.to_string(index=False))
    else:
        print("\n宽表文件未生成。")
        return 1

    print("\n--- 摘要 ---")
    print(json.dumps({
        "workflow_id": wf_id,
        "input_files": ["orders.xlsx", "customers.xlsx", "products.xlsx"],
        "output_file": str(output_path),
        "rows": result.get("rows"),
        "columns": result.get("columns"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run_demo())
