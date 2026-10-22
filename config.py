import os
from pathlib import Path
from typing import Dict, List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    # Telegram Bot Token & Admins (loaded securely from .env or environment variables)
    BOT_TOKEN: str = ""
    ADMIN_IDS: str = ""
    ADMIN_IDS_RAW: str = ""
    ADMIN_USERNAME: str = ""
    BOT_STORAGE_URL: str = ""
    
    # App & Server Configuration
    BASE_URL: str = ""
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    
    # Database & Storage
    DATABASE_URL: str = ""
    UPLOAD_DIR_RAW: str = Field(default="", validation_alias="UPLOAD_DIR")
    STATIC_DIR_RAW: str = ""
    CORS_ORIGINS: str = ""
    
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def UPLOAD_DIR(self) -> Path:
        configured = self.UPLOAD_DIR_RAW
        if configured:
            return Path(configured).expanduser().resolve()
        disk_path = os.getenv("RENDER_DISK_PATH", "")
        root = Path(disk_path).expanduser() if disk_path else BASE_DIR
        return (root / "uploads").resolve()

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        disk_path = os.getenv("RENDER_DISK_PATH")
        if disk_path:
            return f"sqlite+aiosqlite:///{Path(disk_path).expanduser() / 'gym16.db'}"
        return f"sqlite+aiosqlite:///{BASE_DIR}/gym16.db"

    @property
    def cors_origins(self) -> List[str]:
        raw = self.CORS_ORIGINS or self.BASE_URL
        return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]

    @property
    def STATIC_DIR(self) -> Path:
        return (BASE_DIR / "static").resolve()

    @property
    def admin_ids(self) -> List[int]:
        raw_val = self.ADMIN_IDS or self.ADMIN_IDS_RAW
        if not raw_val:
            return []
        ids = []
        for item in str(raw_val).split(","):
            cleaned = item.strip()
            if cleaned.isdigit():
                ids.append(int(cleaned))
        return ids

    @property
    def admin_usernames(self) -> List[str]:
        raw_val = self.ADMIN_USERNAME
        if not raw_val:
            return []
        return [u.strip().lower().lstrip("@") for u in str(raw_val).split(",") if u.strip()]

settings = Settings()

# Official bell schedule (Gymnasium 16) from timetable sheet
DEFAULT_BELLS = [
    {"lesson_number": 1, "start_time": "08:15", "end_time": "08:55"},
    {"lesson_number": 2, "start_time": "09:10", "end_time": "09:50"},
    {"lesson_number": 3, "start_time": "10:10", "end_time": "10:50"},
    {"lesson_number": 4, "start_time": "11:10", "end_time": "11:50"},
    {"lesson_number": 5, "start_time": "12:10", "end_time": "12:50"},
    {"lesson_number": 6, "start_time": "13:00", "end_time": "13:40"},
    {"lesson_number": 7, "start_time": "13:50", "end_time": "14:30"},
    {"lesson_number": 8, "start_time": "14:40", "end_time": "15:20"},
]

# Classes of the 11th grade parallel
DEFAULT_CLASSES = ["11А", "11Б", "11В", "11Г", "11Д", "11Ж"]

# Profiles mapping by class
CLASS_PROFILES_MAP: Dict[str, List[str]] = {
    "11А": ["Соц-гум", "Филологический"],
    "11Б": ["Физмат"],
    "11В": ["Инфотех", "Инженерный"],
    "11Г": ["Химбио"],
    "11Д": ["Инфотех"],
    "11Ж": ["Инфотех"],
}

ALL_PROFILES: List[str] = [
    "Соц-гум",
    "Филологический",
    "Физмат",
    "Инфотех",
    "Инженерный",
    "Химбио"
]
