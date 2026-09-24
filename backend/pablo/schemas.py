from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(Strict):
    name: str = Field(default="Pablo", min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=256)


class Record(Strict):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=20000)
    project_id: str | None = None
    status: str = "TODO"
    priority: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    due: str = ""
    category: Literal["user", "project", "conversation", "knowledge"] = "user"
    pinned: bool = False
    dependencies: list[str] = Field(default_factory=list, max_length=30)
    repository: str = Field(default="", max_length=250)
    version: int | None = None


class Command(Strict):
    goal: str = Field(min_length=1, max_length=12000)
    mode: Literal["ASK", "PLAN", "DO", "RESEARCH", "CHAT"] = "ASK"
    project_id: str | None = None
    conversation_id: str | None = None


class Settings(Strict):
    name: str = Field(default="Pablo", min_length=1, max_length=100)
    timezone: str = "Europe/Madrid"
    autonomy: Literal["MANUAL", "ASSISTED", "AUTONOMOUS"] = "ASSISTED"
    memory_enabled: bool = True
    memory_categories: list[Literal["user", "project", "conversation", "knowledge"]] = Field(
        default_factory=lambda: ["user", "project", "knowledge"]
    )
    demo: bool = False


class Decision(Strict):
    approve: bool


class Step(Strict):
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list)

    @field_validator("tool")
    @classmethod
    def registered_tool(cls, value):
        from .tools import registry

        registry.get(value)
        return value


class Plan(Strict):
    summary: str = Field(max_length=15000)
    steps: list[Step] = Field(max_length=8)


class ScheduledCommand(Strict):
    title: str = Field(min_length=1, max_length=300)
    goal: str = Field(min_length=1, max_length=12000)
    mode: Literal["ASK", "PLAN", "DO", "RESEARCH", "CHAT"] = "CHAT"
    project_id: str | None = None
    run_at: str
    interval_minutes: int = Field(default=0, ge=0, le=10080)


class Enabled(Strict):
    enabled: bool
