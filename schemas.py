from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

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
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None

class UserProfileUpdate(BaseModel):
    class_name: str = Field(..., description="11А, 11Б, 11В, 11Г, 11Д, 11Ж")
    profile_name: str = Field(..., description="Соц-гум, Филологический, Физмат, etc.")
    first_name: str = Field(..., min_length=2, description="Имя ученика (обязательно)")
    last_name: str = Field(..., min_length=2, description="Фамилия ученика (обязательно)")
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
    is_onboarded: bool = False

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
    slots: List[LessonSlot]

# -------------------------------------------------------------
# News Feed & Social Schemas
# -------------------------------------------------------------
class NewsCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    content: str = Field(..., min_length=5)
    image_url: Optional[str] = None
    author_id: Optional[int] = 1097947498
    author_name: Optional[str] = "Гимназист"
    author_class: Optional[str] = None
    is_anonymous: bool = False

class NewsEditRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    content: str = Field(..., min_length=5)
    admin_id: int

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
    is_anonymous: bool = False
    status: str
    created_at: str
    reactions: List[ReactionCount]
    comments_count: int

class ReactionToggleRequest(BaseModel):
    user_id: int
    emoji: str = Field(..., pattern=r"^(❤️|🔥|👍|👎|🤡|😢)$")

class CommentCreateRequest(BaseModel):
    user_id: int
    author_name: str
    author_class: Optional[str] = None
    text: str = Field(..., min_length=1, max_length=1000)

class CommentResponse(BaseModel):
    id: int
    post_id: int
    user_id: int
    author_name: str
    author_class: Optional[str] = None
    text: str
    created_at: str

class ModerationActionRequest(BaseModel):
    action: str = Field(..., pattern=r"^(approve|reject)$")
    admin_id: int

class UserAdminItem(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    class_name: Optional[str] = None
    profile_name: Optional[str] = None
    is_admin: bool
    is_onboarded: bool
    created_at: Optional[str] = None

class EgeSubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    icon: str
    tasks_count: int

class EgeMaterialCreateRequest(BaseModel):
    subject_code: str
    task_number: int
    title: str = Field(..., min_length=2, max_length=255)
    theory: str = Field(..., min_length=2)
    image_url: Optional[str] = None
    link_url: Optional[str] = None
    admin_id: int

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
