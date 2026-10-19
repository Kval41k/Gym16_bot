from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, 
    Index, Integer, String, Text, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

class User(Base):
    """
    User model representing a gymnasium student or administrator.
    Synced from Telegram WebApp initData.
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    photo_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    
    # Gymnasium student metadata
    class_name: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)  # e.g. "11А"
    profile_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True) # e.g. "Физмат"
    subgroup: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=1) # 1 or 2
    
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    news_posts: Mapped[List["NewsPost"]] = relationship("NewsPost", back_populates="author")
    reactions: Mapped[List["Reaction"]] = relationship("Reaction", back_populates="user", cascade="all, delete-orphan")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User id={self.id} name='{self.first_name}' class='{self.class_name}' profile='{self.profile_name}'>"


class SchoolClass(Base):
    """
    List of classes in the parallel (e.g., 11А, 11Б, 11В).
    """
    __tablename__ = "school_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)

    def __repr__(self) -> str:
        return f"<SchoolClass {self.name}>"


class Profile(Base):
    """
    Specialized educational profiles (e.g. Физмат, Инфотех, Соцэконом, Химбио).
    """
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<Profile {self.name}>"


class BellSchedule(Base):
    """
    Gymnasium bell schedule for lesson timing and live progress calculation.
    """
    __tablename__ = "bell_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lesson_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    start_time: Mapped[str] = mapped_column(String(10), nullable=False)  # "08:30"
    end_time: Mapped[str] = mapped_column(String(10), nullable=False)    # "09:15"
    is_saturday: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("lesson_number", "is_saturday", name="uq_lesson_bell"),
    )

    def __repr__(self) -> str:
        return f"<BellSchedule #{self.lesson_number} {self.start_time}-{self.end_time}>"


class Lesson(Base):
    """
    A single lesson entry in the schedule.
    Supports parallel tracks, profiles, and subgroups.
    - If profile_name is NULL & subgroup is NULL: General lesson for whole class.
    - If profile_name is set: Only for students of this profile.
    - If subgroup is set (1 or 2): Only for students of this subgroup.
    """
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # 0=Пн, 1=Вт, 2=Ср, 3=Чт, 4=Пт, 5=Сб
    lesson_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True) # 1..8
    class_name: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # "11А", "11Б", "11В"
    
    subject: Mapped[str] = mapped_column(String(150), nullable=False)
    teacher_name: Mapped[str] = mapped_column(String(150), nullable=False)
    cabinet: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Profile & Subgroup targeting
    profile_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    subgroup: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) # 1, 2, or NULL
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_lessons_lookup", "class_name", "day_of_week", "lesson_number"),
    )

    def __repr__(self) -> str:
        prof = f" [{self.profile_name}]" if self.profile_name else ""
        sub = f" (гр.{self.subgroup})" if self.subgroup else ""
        return f"<Lesson {self.class_name} d{self.day_of_week} #{self.lesson_number}: {self.subject}{prof}{sub} @ {self.cabinet}>"


class NewsPost(Base):
    """
    News feed posts. Suggested posts start as 'pending' for moderation.
    Once approved by an admin, status becomes 'approved' and appears in the feed.
    """
    __tablename__ = "news_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    
    author_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    author_name: Mapped[str] = mapped_column(String(100), nullable=False)
    author_class: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Moderation status: 'pending', 'approved', 'rejected'
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    author: Mapped[Optional["User"]] = relationship("User", back_populates="news_posts")
    reactions: Mapped[List["Reaction"]] = relationship(
        "Reaction", back_populates="post", cascade="all, delete-orphan", lazy="selectin"
    )
    comments: Mapped[List["Comment"]] = relationship(
        "Comment", back_populates="post", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<NewsPost id={self.id} title='{self.title[:20]}' status='{self.status}'>"


class Reaction(Base):
    """
    Quick emoji reactions on news posts (e.g. ❤️, 🔥, 👍).
    """
    __tablename__ = "reactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("news_posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    emoji: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    post: Mapped["NewsPost"] = relationship("NewsPost", back_populates="reactions")
    user: Mapped["User"] = relationship("User", back_populates="reactions")

    __table_args__ = (
        UniqueConstraint("post_id", "user_id", "emoji", name="uq_post_user_emoji"),
    )

    def __repr__(self) -> str:
        return f"<Reaction post={self.post_id} user={self.user_id} {self.emoji}>"


class Comment(Base):
    """
    Comments under news posts.
    """
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("news_posts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_name: Mapped[str] = mapped_column(String(100), nullable=False)
    author_class: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    post: Mapped["NewsPost"] = relationship("NewsPost", back_populates="comments")
    user: Mapped["User"] = relationship("User", back_populates="comments")

    def __repr__(self) -> str:
        return f"<Comment post={self.post_id} by='{self.author_name}'>"


class EgeSubject(Base):
    """
    EGE Subjects: Русский язык, Математика, etc.
    """
    __tablename__ = "ege_subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)  # "russian", "math"
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # "Русский язык", "Математика"
    icon: Mapped[str] = mapped_column(String(20), default="📖")
    tasks_count: Mapped[int] = mapped_column(Integer, default=27)

    materials: Mapped[List["EgeMaterial"]] = relationship(
        "EgeMaterial", back_populates="subject", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<EgeSubject {self.code}: {self.name}>"


class EgeMaterial(Base):
    """
    EGE preparation materials and theory per task number.
    """
    __tablename__ = "ege_materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_code: Mapped[str] = mapped_column(
        String(50), ForeignKey("ege_subjects.code", ondelete="CASCADE"), nullable=False, index=True
    )
    task_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # 1..27
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    theory: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    link_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    subject: Mapped["EgeSubject"] = relationship("EgeSubject", back_populates="materials")

    def __repr__(self) -> str:
        return f"<EgeMaterial #{self.task_number} {self.title}>"
