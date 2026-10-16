from pydantic import BaseModel, Field, model_validator
from typing import Optional
from datetime import datetime


class LoginRequest(BaseModel):
    login: str = Field(..., min_length=1, description="Employee number or email")
    password: str = Field(..., min_length=1)


class RegisterRequest(BaseModel):
    employee_no: Optional[str] = Field(None, max_length=64)
    email: Optional[str] = Field(None, max_length=255)
    password: str = Field(..., min_length=6)
    display_name: str = Field(..., min_length=1, max_length=255)

    @model_validator(mode="after")
    def require_login_id(self):
        if not self.employee_no and not self.email:
            raise ValueError("employee_no or email is required")
        return self


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6)


class AdminResetPasswordRequest(BaseModel):
    login: str = Field(..., min_length=1, description="Employee number or email")
    new_password: str = Field(..., min_length=6)


class ForgotPasswordRequest(BaseModel):
    login: str = Field(..., min_length=1, description="Employee number or email")


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=6)


class MessageResponse(BaseModel):
    message: str


class UserMailboxCreate(BaseModel):
    email: Optional[str] = Field(None, max_length=255)
    mailbox_password: Optional[str] = Field(None, min_length=1)
    imap_host: Optional[str] = Field(None, max_length=255)
    imap_port: Optional[int] = Field(None, ge=1, le=65535)
    imap_use_ssl: Optional[bool] = True


class UserMailboxResponse(BaseModel):
    id: str
    email: str
    imap_host: str
    imap_port: int
    imap_use_ssl: bool
    is_active: bool
    password_preview: str

    class Config:
        from_attributes = True


class UserMailboxTestResponse(BaseModel):
    ok: bool
    message: str
    sample_count: int = 0


class UserResponse(BaseModel):
    id: str
    employee_no: Optional[str] = None
    email: Optional[str] = None
    display_name: str
    is_active: bool
    is_admin: bool = False
    created_at: datetime
    primary_department: Optional["DepartmentBrief"] = None
    roles: list["RoleAssignmentResponse"] = []
    permissions: list[str] = []
    data_scope: str = "self"

    class Config:
        from_attributes = True


class DepartmentBrief(BaseModel):
    id: str
    name: str
    code: Optional[str] = None
    path: str


class RoleAssignmentResponse(BaseModel):
    role_code: str
    role_label_zh: str
    role_label_en: str
    scope_department_id: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UserModelKeyCreate(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    model_id: Optional[str] = Field(None, max_length=128)
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = Field(None, max_length=512)
    is_default: bool = False


class UserModelKeyTest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    model_id: str = Field(..., min_length=1, max_length=128)
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = Field(None, max_length=512)


class UserModelKeyResponse(BaseModel):
    id: str
    provider: str
    model_id: Optional[str] = None
    base_url: Optional[str] = None
    is_active: bool
    is_default: bool = False
    api_key_preview: str

    class Config:
        from_attributes = True
