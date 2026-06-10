from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from app.db.session import get_db
from app.db.models import User, UserModelCredential, UserMailboxCredential
from app.db.base import generate_uuid
from app.core.auth.security import hash_password, verify_password, create_access_token
from app.core.auth.deps import get_current_user, get_current_admin_user
from app.core.email.password_reset import create_and_send_reset, validate_reset_token, consume_reset_token
from app.core.email.mailbox_service import fetch_user_mailbox, get_user_mailbox, mailbox_imap_settings
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    UserModelKeyCreate,
    UserModelKeyResponse,
    ChangePasswordRequest,
    AdminResetPasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    MessageResponse,
    UserMailboxCreate,
    UserMailboxResponse,
    UserMailboxTestResponse,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def _serialize_key(row: UserModelCredential) -> UserModelKeyResponse:
    return UserModelKeyResponse(
        id=row.id,
        provider=row.provider,
        model_id=row.model_id,
        base_url=row.base_url,
        is_active=row.is_active,
        api_key_preview=_mask_key(row.api_key),
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    login_id = payload.login.strip()
    email_id = login_id.lower()

    result = await db.execute(
        select(User).where(
            or_(
                User.employee_no == login_id,
                func.lower(User.employee_no) == login_id.lower(),
                User.email == email_id,
            )
        ).limit(1)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User inactive")
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if payload.employee_no:
        dup = await db.execute(select(User).where(User.employee_no == payload.employee_no.strip()))
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Employee number already registered")
    if payload.email:
        dup = await db.execute(select(User).where(User.email == payload.email.strip().lower()))
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        id=generate_uuid(),
        employee_no=payload.employee_no.strip() if payload.employee_no else None,
        email=payload.email.strip().lower() if payload.email else None,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    await db.flush()


@router.post("/admin/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def admin_reset_password(
    payload: AdminResetPasswordRequest,
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    login_id = payload.login.strip()
    email_id = login_id.lower()
    result = await db.execute(
        select(User).where(
            or_(User.employee_no == login_id, User.email == email_id)
        ).limit(1)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    target.password_hash = hash_password(payload.new_password)
    await db.flush()


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    login_id = payload.login.strip()
    email_id = login_id.lower()
    result = await db.execute(
        select(User).where(
            or_(
                User.employee_no == login_id,
                func.lower(User.employee_no) == login_id.lower(),
                User.email == email_id,
            )
        ).limit(1)
    )
    user = result.scalar_one_or_none()
    if user:
        try:
            await create_and_send_reset(db, user)
            await db.commit()
        except Exception:
            await db.rollback()
    return MessageResponse(
        message="If the account exists and has a valid email, a reset link has been sent."
    )


@router.get("/reset-password/validate", response_model=MessageResponse)
async def validate_reset_password_token(token: str, db: AsyncSession = Depends(get_db)):
    user = await validate_reset_token(db, token)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    return MessageResponse(message="Token is valid")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    ok = await consume_reset_token(db, payload.token, hash_password(payload.new_password))
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    await db.commit()
    return MessageResponse(message="Password has been reset. You can sign in now.")


def _serialize_mailbox(row: UserMailboxCredential) -> UserMailboxResponse:
    preview = row.mailbox_password
    if len(preview) <= 4:
        masked = "****"
    else:
        masked = f"{preview[:2]}...{preview[-2:]}"
    host, port, use_ssl = mailbox_imap_settings(row)
    return UserMailboxResponse(
        id=row.id,
        email=row.email,
        imap_host=host,
        imap_port=port,
        imap_use_ssl=use_ssl,
        is_active=row.is_active,
        password_preview=masked,
    )


@router.get("/me/mailbox", response_model=UserMailboxResponse | None)
async def get_my_mailbox(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await get_user_mailbox(db, user.id)
    return _serialize_mailbox(row) if row else None


@router.post("/me/mailbox", response_model=UserMailboxResponse, status_code=status.HTTP_201_CREATED)
async def save_my_mailbox(
    payload: UserMailboxCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    email = (payload.email or user.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required")

    row = await get_user_mailbox(db, user.id)
    if row:
        row.email = email
        row.mailbox_password = payload.mailbox_password.strip()
        row.imap_host = (payload.imap_host or "").strip() or None
        row.imap_port = payload.imap_port
        row.imap_use_ssl = True if payload.imap_use_ssl is None else payload.imap_use_ssl
        row.is_active = True
    else:
        row = UserMailboxCredential(
            id=generate_uuid(),
            user_id=user.id,
            email=email,
            mailbox_password=payload.mailbox_password.strip(),
            imap_host=(payload.imap_host or "").strip() or None,
            imap_port=payload.imap_port,
            imap_use_ssl=True if payload.imap_use_ssl is None else payload.imap_use_ssl,
            is_active=True,
        )
        db.add(row)
    await db.flush()
    await db.refresh(row)
    return _serialize_mailbox(row)


@router.delete("/me/mailbox", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_mailbox(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await get_user_mailbox(db, user.id)
    if row:
        row.is_active = False
        await db.flush()


@router.post("/me/mailbox/test", response_model=UserMailboxTestResponse)
async def test_my_mailbox(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        messages = await fetch_user_mailbox(user.id, limit=3, db=db)
        return UserMailboxTestResponse(
            ok=True,
            message="Mailbox connection successful",
            sample_count=len(messages),
        )
    except Exception as exc:
        return UserMailboxTestResponse(ok=False, message=str(exc), sample_count=0)


@router.get("/me/model-keys", response_model=list[UserModelKeyResponse])
async def list_my_model_keys(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserModelCredential)
        .where(UserModelCredential.user_id == user.id, UserModelCredential.is_active == True)
        .order_by(UserModelCredential.provider, UserModelCredential.model_id)
    )
    return [_serialize_key(r) for r in result.scalars().all()]


@router.post("/me/model-keys", response_model=UserModelKeyResponse, status_code=status.HTTP_201_CREATED)
async def upsert_my_model_key(
    payload: UserModelKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    provider = payload.provider.strip().lower()
    model_id = payload.model_id.strip() if payload.model_id else None
    result = await db.execute(
        select(UserModelCredential).where(
            UserModelCredential.user_id == user.id,
            UserModelCredential.provider == provider,
            UserModelCredential.model_id == model_id,
        ).limit(1)
    )
    row = result.scalar_one_or_none()
    if row:
        row.api_key = payload.api_key.strip()
        row.base_url = (payload.base_url or "").strip() or None
        row.is_active = True
    else:
        row = UserModelCredential(
            id=generate_uuid(),
            user_id=user.id,
            provider=provider,
            model_id=model_id,
            api_key=payload.api_key.strip(),
            base_url=(payload.base_url or "").strip() or None,
            is_active=True,
        )
        db.add(row)
    await db.flush()
    await db.refresh(row)
    from app.models_hub.router import ModelRouter
    ModelRouter.clear_cache()
    return _serialize_key(row)


@router.delete("/me/model-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_model_key(
    key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(UserModelCredential, key_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Model key not found")
    row.is_active = False
    await db.flush()
    from app.models_hub.router import ModelRouter
    ModelRouter.clear_cache()
