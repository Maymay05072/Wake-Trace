from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WAKETRACE_",
        extra="ignore",
    )

    api_key: str = ""
    api_base_url: str = "https://api.example.com/v1/chat/completions"
    model: str = "your-model-name"
    admin_token: str = ""
    web_token: str = ""
    mcp_token: str = ""
    mcp_allow_write: bool = False
    mcp_allow_wake: bool = False
    mcp_allowed_hosts: str = "127.0.0.1,127.0.0.1:*,localhost,localhost:*"
    scheduler_enabled: bool = True
    db_path: Path = Path("./data/waketrace.db")
    web_dist_path: Path = Path("./web/dist/client")
    web_origins: str = ""

    # 醒来时的“手”：网页、接口、文件、命令。关掉即回到只有线头和作品的状态。
    hands_enabled: bool = True
    hands_read_roots: str = (
        "/sdcard/Download/Operit:"
        "/data/user/0/com.ai.assistance.operit/files/workspace"
    )
    hands_write_roots: str = "/sdcard/Download/Operit"
    hands_allow_commands: bool = True
    hands_command_timeout_seconds: int = Field(default=20, ge=1, le=120)
    hands_max_chars: int = Field(default=4000, ge=200, le=20000)
    hands_secrets_file: Path = Path.home() / ".waketrace_secrets.env"
    hands_task_dir: Path = Path("/sdcard/Download/Operit/wake_tasks")

    companion_name: str = "Companion"
    user_name: str = "User"
    timezone: str = "UTC"

    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=1200, ge=128, le=8192)
    max_tool_rounds: int = Field(default=4, ge=0, le=8)
    recent_fact_limit: int = Field(default=8, ge=1, le=30)
    residue_ttl_hours: int = Field(default=24, ge=1, le=168)

    min_interval_minutes: int = Field(default=30, ge=5, le=1440)
    max_interval_minutes: int = Field(default=120, ge=10, le=2880)
    night_min_interval_minutes: int = Field(default=120, ge=10, le=2880)
    max_wakes_per_day: int = Field(default=15, ge=1, le=100)
    quiet_hours_start: int = Field(default=23, ge=0, le=23)
    quiet_hours_end: int = Field(default=7, ge=0, le=23)

    vapid_private_key: str = ""
    vapid_claims_email: str = "mailto:admin@example.com"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("max_interval_minutes")
    @classmethod
    def interval_order(cls, value: int, info):
        minimum = info.data.get("min_interval_minutes", 30)
        if value < minimum:
            raise ValueError("max_interval_minutes must be >= min_interval_minutes")
        return value

    def ensure_runtime_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
