"""Yiriba SaaS — Student Pydantic schemas.

school_id n'est JAMAIS dans les schémas client — il vient du JWT côté serveur.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ParentRole, StudentStatus


# ── CRUD ──────────────────────────────────────────────────────────


class StudentCreate(BaseModel):
    """Schema for creating a student. No school_id — comes from JWT."""
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    matricule: str = Field(default="", max_length=30)
    birth_date: Optional[date] = None
    birth_place: Optional[str] = Field(default=None, max_length=100)
    nationality: str = Field(default="Burkinabe", max_length=60)
    gender: str = Field(default="M", pattern="^[MF]$")
    address: Optional[str] = None
    phone: Optional[str] = Field(default=None, max_length=30)
    previous_school: Optional[str] = Field(default=None, max_length=200)
    is_repeater: bool = False
    medical_info: Optional[str] = None

    # ── Parent (optionnel à la création) ────────────────────────
    parent_first_name: Optional[str] = Field(default=None, max_length=100)
    parent_last_name: Optional[str] = Field(default=None, max_length=100)
    parent_phone: Optional[str] = Field(default=None, max_length=30)
    parent_email: Optional[str] = Field(default=None, max_length=200)
    parent_role: Optional[str] = Field(default=None, pattern="^(father|mother|guardian|other)$")
    parent_is_primary: bool = True

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class StudentUpdate(BaseModel):
    """Schema for updating a student — all fields optional."""
    first_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    matricule: Optional[str] = Field(default=None, max_length=30)
    birth_date: Optional[date] = None
    birth_place: Optional[str] = Field(default=None, max_length=100)
    nationality: Optional[str] = Field(default=None, max_length=60)
    gender: Optional[str] = Field(default=None, pattern="^[MF]$")
    address: Optional[str] = None
    phone: Optional[str] = Field(default=None, max_length=30)
    previous_school: Optional[str] = Field(default=None, max_length=200)
    is_repeater: Optional[bool] = None
    medical_info: Optional[str] = None
    photo_url: Optional[str] = None


class StudentStatusUpdate(BaseModel):
    """Schema for changing student status (soft delete / transfer / graduate)."""
    status: StudentStatus
    reason: str = Field(default="", max_length=200)


# ── Transfer ──────────────────────────────────────────────────────


class StudentTransfer(BaseModel):
    """Schema for transferring a student to a new class."""
    new_class_id: int
    reason: str = Field(default="", max_length=200)


# ── Parent Links ──────────────────────────────────────────────────


class ParentLinkCreate(BaseModel):
    """Schema for linking a parent to a student."""
    parent_id: int
    role: ParentRole = ParentRole.OTHER
    is_primary: bool = False


class ParentLinkResponse(BaseModel):
    """Schema for parent link response."""
    id: int
    parent_id: int
    parent_name: str
    role: ParentRole
    is_primary: bool

    model_config = {"from_attributes": True}


# ── Response ──────────────────────────────────────────────────────


class StudentResponse(BaseModel):
    """Schema for student response."""
    id: int
    school_id: int
    matricule: str
    first_name: str
    last_name: str
    birth_date: Optional[date] = None
    birth_place: Optional[str] = None
    nationality: str
    gender: str
    address: Optional[str] = None
    phone: Optional[str] = None
    photo_url: Optional[str] = None
    previous_school: Optional[str] = None
    is_repeater: bool
    status: StudentStatus
    status_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    current_class: Optional[str] = None
    current_year: Optional[str] = None
    parents: list[ParentLinkResponse] = []
    user_id: Optional[int] = None
    account_username: Optional[str] = None
    account_exists: bool = False

    model_config = {"from_attributes": True}


class StudentListResponse(BaseModel):
    """Paginated list of students."""
    students: list[StudentResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class StudentHistoryResponse(BaseModel):
    """Complete student history: enrollments, classes, status changes."""
    student: StudentResponse
    enrollments: list[dict]
    status_history: list[dict]
