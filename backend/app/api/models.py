from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import get_db
from app.db.models import ModelConfig, User
from app.db.base import generate_uuid
from app.models_hub.router import ModelRouter
from app.core.auth.deps import get_current_user
from app.schemas.model import (
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelConfigResponse,
    ModelConnectionTestRequest,
    ModelConnectionTestResponse,
    build_config_payload,
    response_inference_params,
)

router = APIRouter(prefix="/models", tags=["Model Hub"])


def _to_response(cfg: ModelConfig) -> ModelConfigResponse:
    return ModelConfigResponse(
        id=cfg.id,
        name=cfg.name,
        provider=cfg.provider,
        model_id=cfg.model_id,
        base_url=cfg.base_url,
        is_default=cfg.is_default,
        is_active=cfg.is_active,
        context_window=cfg.context_window,
        cost_per_1k_input=cfg.cost_per_1k_input,
        cost_per_1k_output=cfg.cost_per_1k_output,
        inference_params=response_inference_params(cfg.config),
        config=cfg.config or {},
    )


async def _ensure_single_default(db: AsyncSession, keep_id: str) -> None:
    result = await db.execute(select(ModelConfig).where(ModelConfig.is_active == True))
    for cfg in result.scalars().all():
        cfg.is_default = cfg.id == keep_id


async def _pick_default_if_missing(db: AsyncSession) -> None:
    result = await db.execute(select(ModelConfig).where(ModelConfig.is_active == True))
    active = result.scalars().all()
    if not active:
        return
    if any(c.is_default for c in active):
        return
    active[0].is_default = True


@router.get("/available")
async def list_available_models():
    """Lists all configured LLM providers and their models."""
    return await ModelRouter.list_available_models()


@router.get("/configs", response_model=list[ModelConfigResponse])
async def list_model_configs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ModelConfig)
        .where(ModelConfig.is_active == True)
        .order_by(ModelConfig.is_default.desc(), ModelConfig.name.asc())
    )
    return [_to_response(c) for c in result.scalars().all()]


@router.post("/configs", response_model=ModelConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_model_config(
    payload: ModelConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    dup = await db.execute(select(ModelConfig).where(ModelConfig.name == payload.name))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Model config name already exists: {payload.name}")

    merged_config = build_config_payload(payload.config, payload.inference_params)

    cfg = ModelConfig(
        id=generate_uuid(),
        name=payload.name.strip(),
        provider=payload.provider.strip().lower(),
        model_id=payload.model_id.strip(),
        base_url=(payload.base_url or "").strip() or None,
        context_window=payload.context_window,
        cost_per_1k_input=payload.cost_per_1k_input,
        cost_per_1k_output=payload.cost_per_1k_output,
        is_default=payload.is_default,
        is_active=True,
        config=merged_config,
    )
    db.add(cfg)
    await db.flush()

    if cfg.is_default:
        await _ensure_single_default(db, cfg.id)
    else:
        await _pick_default_if_missing(db)

    await db.flush()
    await db.refresh(cfg)
    ModelRouter.clear_cache()
    return _to_response(cfg)


@router.patch("/configs/{config_id}", response_model=ModelConfigResponse)
async def update_model_config(
    config_id: str,
    payload: ModelConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    cfg = await db.get(ModelConfig, config_id)
    if not cfg or not cfg.is_active:
        raise HTTPException(status_code=404, detail="Model config not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != cfg.name:
        dup = await db.execute(
            select(ModelConfig).where(ModelConfig.name == data["name"], ModelConfig.id != config_id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Model config name already exists: {data['name']}")

    inference_params = payload.inference_params if payload.inference_params is not None else None
    data.pop("inference_params", None)
    config_override = data.pop("config", None)

    for field, value in data.items():
        if field == "provider" and isinstance(value, str):
            value = value.strip().lower()
        if field in ("name", "model_id", "base_url") and isinstance(value, str):
            value = value.strip()
            if field == "base_url" and not value:
                value = None
        setattr(cfg, field, value)

    if inference_params is not None or config_override is not None:
        base_config = config_override if config_override is not None else (cfg.config or {})
        cfg.config = build_config_payload(base_config, inference_params)
        flag_modified(cfg, "config")

    if data.get("is_default"):
        await _ensure_single_default(db, cfg.id)
    elif "is_default" in data and data["is_default"] is False and cfg.is_default:
        cfg.is_default = False
        await _pick_default_if_missing(db)

    await db.flush()
    await db.refresh(cfg)
    ModelRouter.clear_cache()
    return _to_response(cfg)


@router.post("/configs/{config_id}/set-default", response_model=ModelConfigResponse)
async def set_default_model_config(config_id: str, db: AsyncSession = Depends(get_db)):
    cfg = await db.get(ModelConfig, config_id)
    if not cfg or not cfg.is_active:
        raise HTTPException(status_code=404, detail="Model config not found")
    cfg.is_default = True
    await _ensure_single_default(db, cfg.id)
    await db.flush()
    await db.refresh(cfg)
    ModelRouter.clear_cache()
    return _to_response(cfg)


@router.post("/test-connection", response_model=ModelConnectionTestResponse)
async def test_model_connection_preview(
    payload: ModelConnectionTestRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models_hub.connectivity import test_model_connection

    result = await test_model_connection(
        provider=payload.provider,
        model_id=payload.model_id,
        base_url=(payload.base_url or "").strip() or None,
        db=db,
        user_id=user.id,
    )
    return ModelConnectionTestResponse(**result)


@router.post("/configs/{config_id}/test-connection", response_model=ModelConnectionTestResponse)
async def test_model_config_connection(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models_hub.connectivity import test_model_connection

    cfg = await db.get(ModelConfig, config_id)
    if not cfg or not cfg.is_active:
        raise HTTPException(status_code=404, detail="Model config not found")

    result = await test_model_connection(
        provider=cfg.provider,
        model_id=cfg.model_id,
        base_url=cfg.base_url,
        db=db,
        user_id=user.id,
    )
    return ModelConnectionTestResponse(**result)


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_config(config_id: str, db: AsyncSession = Depends(get_db)):
    cfg = await db.get(ModelConfig, config_id)
    if not cfg or not cfg.is_active:
        raise HTTPException(status_code=404, detail="Model config not found")

    was_default = cfg.is_default
    cfg.is_active = False
    cfg.is_default = False
    await db.flush()

    if was_default:
        await _pick_default_if_missing(db)
        await db.flush()
    ModelRouter.clear_cache()
