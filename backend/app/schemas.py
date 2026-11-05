from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if not 8 <= len(key) <= 256 or any(c.isspace() for c in key):
            raise ValueError("请输入有效的 DeepSeek API Key")
        return SecretStr(key)


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(Credentials):
    question: str = Field(min_length=1, max_length=2000)
    model: str = Field(default="deepseek-flash", pattern=r"^deepseek-[a-zA-Z0-9._-]{1,80}$")
    history: list[HistoryMessage] = Field(default_factory=list, max_length=20)
    top_k: int = Field(default=4, ge=1, le=8)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=4, max_length=120)
    content: str = Field(min_length=1, max_length=1_000_000)
