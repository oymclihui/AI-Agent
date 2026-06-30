from langchain_core.tools import tool


@tool
async def batch_parse_excel(
    data_source_id: str,
    template_id: str = "",
    recursive: bool = True,
    folder_path: str = "",
) -> str:
    """
    Batch-parse Excel files using a cell-mapping template and produce a wide table for data Q&A.

    Use when the user wants to extract fixed cells from many similar Excel files (e.g. financial BS/PL reports)
    and load the result into an excel_template data source for questioning.

    Args:
        data_source_id: excel_template data source id (must already exist)
        template_id: parse template id; if empty, uses the template configured on the data source
        recursive: scan subfolders when using folder_path or uploaded input files
        folder_path: optional server directory with source Excel files (otherwise uses uploaded input/)
    """
    from app.core.auth.context import get_current_user_id
    from app.core.excel_parser.service import create_parse_job
    from app.db.models import DataSource
    from app.db.session import AsyncSessionLocal

    user_id = get_current_user_id()
    if not user_id:
        return "Error: no user context. Run from an authenticated agent session."

    async with AsyncSessionLocal() as db:
        source = await db.get(DataSource, data_source_id)
        if not source:
            return f"Error: data source not found: {data_source_id}"
        if str(source.driver) != "excel_template":
            return f"Error: data source must use excel_template driver, got {source.driver}"

        meta = source.metadata_ or {}
        tpl_id = (template_id or "").strip() or str(meta.get("template_id") or "")
        if not tpl_id:
            return "Error: template_id required (pass explicitly or set on data source metadata)."

        try:
            job = await create_parse_job(
                db,
                owner_id=user_id,
                template_id=tpl_id,
                data_source_id=data_source_id,
                folder_path=folder_path.strip() or None,
                recursive=recursive,
            )
        except ValueError as exc:
            return f"Error: {exc}"

    return (
        f"Excel batch parse started.\n"
        f"- job_id: {job.id}\n"
        f"- data_source_id: {data_source_id}\n"
        f"- template_id: {tpl_id}\n"
        f"Poll GET /api/v1/excel-parser/jobs/{job.id} for status. "
        f"When completed, ask questions against this data source."
    )


BatchParseExcelTool = batch_parse_excel
