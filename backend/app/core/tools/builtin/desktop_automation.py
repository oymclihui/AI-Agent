from langchain_core.tools import tool


@tool
async def desktop_list_demos() -> str:
    """
    List available desktop GUI automation demos recorded on the user's PC.
    Use before replay when you need to know exact demo names.
    """
    from app.core.auth.context import get_current_user_id
    from app.core.desktop.service import list_demos_text

    user_id = get_current_user_id()
    if not user_id:
        return "Error: no user context. Run from an authenticated agent session."
    return await list_demos_text(user_id)


DesktopListDemosTool = desktop_list_demos


@tool
async def desktop_replay(demo_name: str, instructions: str = "") -> str:
    """
    Replay a recorded desktop GUI demo on the user's local Windows machine via the desktop sidecar.
    Args:
        demo_name: Exact name of the demo (use desktop_list_demos first if unsure).
        instructions: Optional extra instructions for this replay run.
    Requires the desktop sidecar (scripts/desktop_sidecar.py) to be running on the same PC.
    """
    from app.core.auth.context import get_current_user_id
    from app.core.desktop.service import replay_demo_for_user

    user_id = get_current_user_id()
    if not user_id:
        return "Error: no user context. Run from an authenticated agent session."

    demo_name = (demo_name or "").strip()
    if not demo_name:
        return "Error: demo_name is required."

    result = await replay_demo_for_user(
        user_id,
        demo_name=demo_name,
        instructions=instructions.strip() or None,
        confirmed=False,
    )
    if result.get("needs_confirmation"):
        return (
            f"{result.get('message')} (task_id={result.get('task_id')}). "
            "Ask the user to confirm in Desktop Automation page or chat confirm bar."
        )
    if result.get("ok"):
        return str(result.get("message") or "Replay completed.")
    return f"Replay failed: {result.get('error', 'unknown error')}"


DesktopReplayTool = desktop_replay


@tool
async def desktop_capture(action: str, demo_name: str = "", app_name: str = "", description: str = "") -> str:
    """
    Start or stop recording a desktop GUI demonstration on the user's local machine.
    Args:
        action: "start" to begin recording, "stop" to finish and save the demo.
        demo_name: Required when action is "stop" — name for the saved demo.
        app_name: Optional target application name (e.g. Excel, SAP GUI).
        description: Optional description of what the demo does.
    Requires the desktop sidecar to be running.
    """
    from app.core.auth.context import get_current_user_id
    from app.core.desktop.service import enqueue_task, get_primary_sidecar, sidecar_is_online, wait_for_task
    from app.db.models import DesktopTaskAction, ExecutionStatus
    from app.db.session import AsyncSessionLocal

    user_id = get_current_user_id()
    if not user_id:
        return "Error: no user context. Run from an authenticated agent session."

    act = (action or "").strip().lower()
    if act not in ("start", "stop"):
        return "Error: action must be 'start' or 'stop'."

    async with AsyncSessionLocal() as db:
        sidecar = await get_primary_sidecar(db, user_id)
        if not sidecar_is_online(sidecar):
            return "Error: desktop sidecar offline. Run scripts/desktop_sidecar.py on this PC."

        if act == "start":
            task_action = DesktopTaskAction.capture_start
            input_data = {"demo_name": demo_name, "app_name": app_name, "description": description}
        else:
            if not demo_name.strip():
                return "Error: demo_name is required when stopping capture."
            task_action = DesktopTaskAction.capture_stop
            input_data = {
                "demo_name": demo_name.strip(),
                "app_name": app_name,
                "description": description,
            }

        task = await enqueue_task(
            db,
            user_id,
            action=task_action,
            input_data=input_data,
            sidecar_id=sidecar.id if sidecar else None,
        )
        await db.commit()
        task_id = task.id

    finished = await wait_for_task(task_id, user_id, timeout_s=90.0)
    if not finished:
        return f"Capture task submitted (id={task_id}) but timed out waiting for sidecar."
    if finished.status == ExecutionStatus.completed:
        if act == "stop" and finished.output_data:
            saved = finished.output_data.get("demo_name") or demo_name
            return f"Capture saved as demo: {saved}"
        return "Capture started. Perform the GUI steps on your desktop, then call desktop_capture with action='stop'."
    return f"Capture failed: {finished.error_message or 'unknown error'}"


DesktopCaptureTool = desktop_capture
