from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class NodeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ModelOption(BaseModel):
    id: str = Field(max_length=200)
    name: str = Field(min_length=1, max_length=100)


class RuntimeProfile(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=60)
    models: list[ModelOption] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_models(self):
        if len({model.id for model in self.models}) != len(self.models):
            raise ValueError("Model IDs must be unique within a profile.")
        return self


class NodeRegister(BaseModel):
    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    profiles: list[RuntimeProfile] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_profiles(self):
        if len({profile.id for profile in self.profiles}) != len(self.profiles):
            raise ValueError("Profile IDs must be unique within a node.")
        return self


class NodePoll(BaseModel):
    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class RuntimeConfig(BaseModel):
    node_id: str = Field(min_length=1, max_length=80)
    profile_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    model: str = Field(default="", max_length=200)


class RuntimeReport(NodePoll):
    agent_id: str = Field(min_length=1, max_length=80)
    run_id: str = Field(pattern=r"^run_[a-f0-9]{32}$")
    state: Literal["starting", "running", "stopped", "failed"]
    pid: int | None = Field(default=None, ge=1)
    error: str = Field(default="", max_length=2000)
