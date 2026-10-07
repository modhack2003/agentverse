from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=1, max_length=20000)
    repo_url: str = Field(default="", max_length=2000)
    auto_plan: bool = True


class ProjectUpdate(BaseModel):
    status: Literal["active", "paused"]


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(default="custom", max_length=60)
    capabilities: list[str] = Field(default_factory=list, max_length=20)


class Heartbeat(BaseModel):
    status: Literal["idle", "working", "offline"] = "idle"


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    channel: str = Field(default="general", pattern=r"^[a-z0-9_-]{1,40}$")
    recipient_id: str | None = None
    task_id: str | None = None


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    priority: Literal["low", "medium", "high"] = "medium"
    kind: Literal["planning", "implementation"] = "implementation"
    dependencies: list[str] = Field(default_factory=list, max_length=50)


class TaskEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    priority: Literal["low", "medium", "high"] | None = None
    dependencies: list[str] | None = Field(default=None, max_length=50)


class WorkSubmit(BaseModel):
    summary: str = Field(min_length=1, max_length=20000)
    branch: str = Field(min_length=1, max_length=250, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
    commit_sha: str = Field(pattern=r"^[a-fA-F0-9]{40,64}$")
    diff: str = Field(default="", max_length=100000)


class PlannedTask(TaskCreate):
    depends_on: list[int] = Field(default_factory=list, max_length=40)


class PlanFinish(BaseModel):
    summary: str = Field(min_length=1, max_length=20000)
    tasks: list[PlannedTask] = Field(min_length=1, max_length=40)


class ReviewCreate(BaseModel):
    decision: Literal["approve", "changes_requested"]
    comment: str = Field(min_length=1, max_length=20000)
    integration_sha: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{40,64}$")


class ReleaseTask(BaseModel):
    reason: str = Field(default="Released for another teammate.", min_length=1, max_length=2000)


class MemoryWrite(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    expected_version: int | None = Field(default=None, ge=1)
