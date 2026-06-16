from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DepartmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=64)
    parent_id: Optional[str] = None
    leader_user_id: Optional[str] = None
    liaison_user_id: Optional[str] = None
    dept_tier: str = "business"
    sort_order: int = 0


class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    code: Optional[str] = Field(None, max_length=64)
    parent_id: Optional[str] = None
    leader_user_id: Optional[str] = None
    liaison_user_id: Optional[str] = None
    dept_tier: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class DepartmentResponse(BaseModel):
    id: str
    name: str
    code: Optional[str] = None
    parent_id: Optional[str] = None
    path: str
    level: int
    leader_user_id: Optional[str] = None
    leader_name: Optional[str] = None
    liaison_user_id: Optional[str] = None
    liaison_name: Optional[str] = None
    dept_tier: str = "business"
    sort_order: int
    is_active: bool
    member_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RoleDefinitionResponse(BaseModel):
    role_code: str
    label_zh: str
    label_en: str
    permissions: list[str]


class UserRoleAssign(BaseModel):
    role_code: str
    scope_department_id: Optional[str] = None


class OrgUserCreate(BaseModel):
    employee_no: str = Field(..., min_length=2, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)
    primary_department_id: Optional[str] = None
    user_tier: str = "staff"
    roles: list[UserRoleAssign] = Field(default_factory=list)
    is_active: bool = True


class OrgUserUpdate(BaseModel):
    primary_department_id: Optional[str] = None
    user_tier: Optional[str] = None
    roles: Optional[list[UserRoleAssign]] = None
    is_active: Optional[bool] = None


class OrgUserResponse(BaseModel):
    id: str
    employee_no: Optional[str] = None
    email: Optional[str] = None
    display_name: str
    is_active: bool
    is_admin: bool
    user_tier: str = "staff"
    primary_department_id: Optional[str] = None
    primary_department_name: Optional[str] = None
    roles: list[UserRoleAssign]
    permissions: list[str] = []
    created_at: datetime


class PermissionPreviewResponse(BaseModel):
    user_id: str
    display_name: str
    roles: list[UserRoleAssign]
    permissions: list[str]
    data_scope: str
    visible_user_count: int
    visible_department_count: int
    can_view_dashboard: bool
    can_manage_org: bool
    department_paths: list[str]


class DelegationContextResponse(BaseModel):
    lane: str
    assignable_roles: list[str]
    department_count: int = 0
    manageable_user_count: int = 0
    department_paths: list[str] = []


class DeptDelegationUpdate(BaseModel):
    primary_department_id: Optional[str] = None
    roles: list[UserRoleAssign] = Field(default_factory=list)


class ExecDelegationUpdate(BaseModel):
    roles: list[UserRoleAssign] = Field(default_factory=list)
    user_tier: Optional[str] = None


class AuditLogResponse(BaseModel):
    id: str
    actor_user_id: str
    actor_name: Optional[str] = None
    target_user_id: str
    target_name: Optional[str] = None
    action: str
    details: dict = {}
    created_at: datetime

    class Config:
        from_attributes = True


class PermissionImportRowResponse(BaseModel):
    row_number: int
    employee_no: str
    display_name: str = ""
    primary_department_code: str = ""
    primary_department_name: str = ""
    user_tier: str = "staff"
    roles: list[str] = Field(default_factory=list)
    scope_department_code: str = ""
    is_active: bool = True
    status: str
    message: str = ""
    user_id: Optional[str] = None
    changes: dict = Field(default_factory=dict)


class PermissionImportPreviewResponse(BaseModel):
    total: int
    ok: int
    warning: int
    error: int
    rows: list[PermissionImportRowResponse]


class PermissionImportApplyRequest(BaseModel):
    rows: list[PermissionImportRowResponse]


class PermissionImportApplyResponse(BaseModel):
    applied: int
    skipped: int
    failed: int
