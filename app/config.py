from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional, List
import re

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    BOT_TOKEN: str
    DATABASE_URL: str
    GROUP_CHAT_ID: int

    BOOKING_HORIZON_DAYS: int = 7
    WORKDAY_START: str = "09:00"
    WORKDAY_END: str = "19:00"
    SLOT_MIN: int = 120

    TIMEZONE: str = "Europe/Amsterdam"
    ADMIN_IDS: Optional[str] = None

    def admin_id_list(self) -> List[int]:
        if not self.ADMIN_IDS:
            return []
        parts = [p.strip() for p in self.ADMIN_IDS.split(",") if p.strip()]
        out = []
        for p in parts:
            if re.fullmatch(r"-?\d+", p):
                out.append(int(p))
        return out

settings = Settings()
