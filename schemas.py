from datetime import datetime
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, field_validator

# -------------------------------------------------------------
# Metadata / Structure Schemas
# -------------------------------------------------------------
class StructureResponse(BaseModel):
    classes: List[str]
    class_profiles: Dict[str, List[str]]
    all_profiles: List[str]

# -------------------------------------------------------------
# User Profile Schemas
# -------------------------------------------------------------
class UserSyncRequest(BaseModel):
    id: int = Field(gt=0, lt=2**63)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    username: Optional[str] = Field(None, max_length=100)
    photo_url: Optional[str] = Field(None, max_length=512)
    class_name: Optional[str] = None
    profile_name: Optional[str] = None

class UserProfileUpdate(BaseModel):
    class_name: str = Field(..., description="11А, 11Б, 11В, 11Г, 11Д, 11Ж")
    profile_name: str = Field(..., description="Соц-гум, Филологический, Физмат, etc.")
    first_name: str = Field(..., min_length=2, max_length=100, description="Имя ученика (обязательно)")
    last_name: str = Field(..., min_length=2, max_length=100, description="Фамилия ученика (обязательно)")
    subgroup: Optional[int] = Field(None, description="Not used")

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    class_name: Optional[str] = None
    profile_name: Optional[str] = None
    subgroup: Optional[int] = None
    is_admin: bool
    role: str = "student"
    headman_class_name: Optional[str] = None
    access_allowed: bool = True
    is_onboarded: bool = False
    is_banned: bool = False

# -------------------------------------------------------------
# Bell & Live Schedule Schemas
# -------------------------------------------------------------
class BellItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lesson_number: int
    start_time: str
    end_time: str

class LiveStatusResponse(BaseModel):
    current_time: str
    state: str  # "lesson", "break", "before_school", "after_school", "weekend"
    current_lesson_number: Optional[int] = None
    minutes_left: Optional[int] = None
    message: str
    next_lesson_number: Optional[int] = None
    next_lesson_time: Optional[str] = None

# -------------------------------------------------------------
# Schedule Schemas
# -------------------------------------------------------------
class LessonItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    day_of_week: int
    lesson_number: int
    class_name: str
    subject: str
    teacher_name: str
    cabinet: str
    profile_name: Optional[str] = None
    subgroup: Optional[int] = None
    note: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None

class LessonSlot(BaseModel):
    lesson_number: int
    start_time: str
    end_time: str
    is_split: bool  # True if slot contains split profiles
    lessons: List[LessonItem]

class DayScheduleResponse(BaseModel):
    day_of_week: int
    day_name: str
    class_name: str
    schedule_loaded: bool = True
    slots: List[LessonSlot]
    date: Optional[str] = None
    is_override: bool = False
    note: str = ""

# -------------------------------------------------------------
# News Feed & Social Schemas
# -------------------------------------------------------------
def _validate_news_image_url(value: Optional[str]) -> Optional[str]:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if len(value) > 512 or any(char in value for char in "\"'<>\\\n\r"):
        raise ValueError("Некорректный адрес изображения")
    if value.startswith("/uploads/"):
        filename = value.removeprefix("/uploads/")
        if filename and "/" not in filename and filename not in {".", ".."}:
            return value
        raise ValueError("Некорректный адрес загруженного изображения")
    if re.fullmatch(r"/api/media/[A-Za-z0-9_-]{10,250}", value):
        return value
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password:
        return value
    raise ValueError("Изображение должно быть загружено в приложение или иметь HTTPS адрес")


class NewsCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    content: str = Field(..., min_length=5, max_length=20000)
    image_url: Optional[str] = None
    author_id: Optional[int] = None
    author_name: Optional[str] = "Гимназист"
    author_class: Optional[str] = None
    author_username: Optional[str] = None
    is_anonymous: bool = False

    @field_validator("title", "content", mode="before")
    @classmethod
    def strip_content(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: Optional[str]) -> Optional[str]:
        return _validate_news_image_url(value)

class NewsEditRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    content: str = Field(..., min_length=5, max_length=20000)
    image_url: Optional[str] = None
    admin_id: Optional[int] = None
    user_id: Optional[int] = None

    @field_validator("title", "content", mode="before")
    @classmethod
    def strip_content(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: Optional[str]) -> Optional[str]:
        return _validate_news_image_url(value)

class ReactionCount(BaseModel):
    emoji: str
    count: int
    user_reacted: bool = False

class NewsResponse(BaseModel):
    id: int
    title: str
    content: str
    image_url: Optional[str] = None
    author_name: str
    author_class: Optional[str] = None
    author_photo_url: Optional[str] = None
    author_username: Optional[str] = None
    is_anonymous: bool = False
    status: str
    created_at: str
    reactions: List[ReactionCount]
    comments_count: int
    is_pinned: bool = False

class ReactionToggleRequest(BaseModel):
    user_id: int
    emoji: str = Field(..., pattern=r"^(❤️|🔥|👍|👎|🤡|😢)$")

class CommentCreateRequest(BaseModel):
    user_id: int
    author_name: str
    author_class: Optional[str] = None
    text: str = Field(..., min_length=1, max_length=1000)

    @field_validator("text", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class CommentEditRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    revision: str = Field(..., pattern=r"^[0-9a-f]{64}$")

    @field_validator("text", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

class CommentResponse(BaseModel):
    id: int
    post_id: int
    user_id: int
    author_name: str
    author_class: Optional[str] = None
    text: str
    created_at: str
    is_edited: bool = False
    updated_at: Optional[str] = None
    revision: str = ""

class ModerationActionRequest(BaseModel):
    action: str = Field(..., pattern=r"^(approve|reject)$")
    admin_id: int
    reason: Optional[str] = Field(None, max_length=1000)
    ts: Optional[int] = None
    sign: Optional[str] = None

class UserAdminItem(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    class_name: Optional[str] = None
    profile_name: Optional[str] = None
    role: str = "student"
    headman_class_name: Optional[str] = None
    is_admin: bool
    is_banned: bool = False
    is_onboarded: bool
    created_at: Optional[str] = None

class UserBanRequest(BaseModel):
    admin_id: int
    is_banned: bool
    ts: Optional[int] = None
    sign: Optional[str] = None

class EgeSubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    icon: str
    tasks_count: int

class EgeMaterialCreateRequest(BaseModel):
    subject_code: str = Field(..., pattern=r"^(russian|math)$")
    task_number: int = Field(..., ge=1, le=27)
    title: str = Field(..., min_length=2, max_length=255)
    theory: str = Field(..., min_length=2, max_length=100000)
    image_url: Optional[str] = Field(None, max_length=512)
    link_url: Optional[str] = Field(None, max_length=512)
    admin_id: int

    @field_validator("title", "theory", mode="before")
    @classmethod
    def strip_content(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("image_url")
    @classmethod
    def validate_image(cls, value):
        return _validate_news_image_url(value)

    @field_validator("link_url")
    @classmethod
    def validate_link(cls, value):
        if not value:
            return None
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or any(c in value for c in '\"\'<>\\\r\n'):
            raise ValueError("Ссылка должна быть безопасным HTTPS адресом")
        return value

class EgeMaterialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject_code: str
    task_number: int
    title: str
    theory: str
    image_url: Optional[str] = None
    link_url: Optional[str] = None
    created_at: str
