from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Financial Research Agent"
    environment: str = "development"
    database_path: Path = Path(".data/finagent.sqlite3")
    sec_identity: str = "Financial Research Agent analyst@example.com"
    sec_requests_per_second: float = Field(default=5.0, ge=0.5, le=10.0)
    request_timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_api_mode: str = "responses"
    llm_max_output_tokens: int = Field(default=4_000, ge=256, le=16_000)
    llm_report_output_tokens: int = Field(default=8_000, ge=256, le=16_000)
    llm_max_retries: int = Field(default=2, ge=0, le=3)

    max_companies: int = Field(default=3, ge=1, le=8)
    max_retrieval_hits: int = Field(default=12, ge=3, le=30)
    agentic_research: bool = True
    agent_max_tool_calls: int = Field(default=60, ge=1, le=200)
    agent_timeout_seconds: int = Field(default=600, ge=10, le=1800)
    web_max_bytes: int = Field(default=2_097_152, ge=1024, le=10_485_760)
    prompt_config_path: Path | None = None
    workspace_root: Path | None = None
    workspace_max_file_bytes: int = Field(default=10_485_760, ge=1024, le=104_857_600)
    workspace_max_total_bytes: int = Field(default=104_857_600, ge=1024)
    workspace_max_files: int = Field(default=200, ge=1, le=10000)
    workspace_max_text_bytes: int = Field(default=262_144, ge=1024, le=1_048_576)


@lru_cache
def get_settings() -> Settings:
    return Settings()
