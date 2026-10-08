from typing import Literal

import re
import math

from pydantic import BaseModel, Field, field_validator, model_validator


def tool_id(value):
    value = value.strip().lower()
    return {"agent zero": "agentzero", "agent-zero": "agentzero", "claude code": "claude", "claude-code": "claude"}.get(value, re.sub(r"[^a-z0-9_-]+", "-", value).strip("-")) or "custom"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


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
    description: str = Field(default="", max_length=5000)
    limitations: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("kind")
    @classmethod
    def normalize_kind(cls, value):
        return tool_id(value)


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
    required_capabilities: list[str] = Field(default_factory=list, max_length=20)


class TaskEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    priority: Literal["low", "medium", "high"] | None = None
    dependencies: list[str] | None = Field(default=None, max_length=50)
    required_capabilities: list[str] | None = Field(default=None, max_length=20)


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
    models: list[ModelOption] = Field(default_factory=lambda: [ModelOption(id="", name="Tool default")], min_length=1, max_length=100)
    mode: Literal["managed_cli", "managed_api", "connected"] = "managed_cli"
    driver: str = Field(default="cli", pattern=r"^[a-z0-9_-]{1,80}$")
    protocol_version: int = Field(default=1, ge=1)
    tool_version: str = Field(default="", max_length=120)
    capabilities: list[str] = Field(default_factory=list, max_length=40)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    availability: Literal["available", "unavailable", "needs_setup"] = "available"
    diagnostic: str = Field(default="", max_length=2000)
    settings_schema: list["SettingField"] = Field(default_factory=list, max_length=40)
    required_settings: list[str] = Field(default_factory=list, max_length=40)
    execution_revision: str = Field(default="", max_length=64)

    @field_validator("kind")
    @classmethod
    def normalize_kind(cls, value):
        return tool_id(value)

    @model_validator(mode="after")
    def unique_models(self):
        if len({model.id for model in self.models}) != len(self.models):
            raise ValueError("Model IDs must be unique within a profile.")
        if len({field.key for field in self.settings_schema}) != len(self.settings_schema):
            raise ValueError("Setting keys must be unique within a profile.")
        validate_settings(self.model_dump(), {})
        return self


class NodeRegister(BaseModel):
    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    profiles: list[RuntimeProfile] = Field(min_length=1, max_length=30)
    protocol_version: int = Field(default=1, ge=1)
    diagnostics: list["Diagnostic"] = Field(default_factory=list, max_length=100)
    capacity: int = Field(default=4, ge=1, le=32)

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
    settings: dict[str, str | float | bool | None] = Field(default_factory=dict)

    @field_validator("settings")
    @classmethod
    def bounded_settings(cls, values):
        if len(values) > 40 or any(len(str(value)) > 5000 for value in values.values()):
            raise ValueError("Too many settings or a setting value is too long.")
        return values


class RuntimeReport(NodePoll):
    agent_id: str = Field(min_length=1, max_length=80)
    run_id: str = Field(pattern=r"^run_[a-f0-9]{32}$")
    state: Literal["starting", "running", "stopped", "failed", "unconfirmed"]
    pid: int | None = Field(default=None, ge=1)
    error: str = Field(default="", max_length=2000)


class SettingField(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,60}$")
    label: str = Field(min_length=1, max_length=100)
    type: Literal["text", "number", "boolean", "choice"] = "text"
    default: str | float | bool | None = None
    options: list[str] = Field(default_factory=list, max_length=100)
    minimum: float | None = None
    maximum: float | None = None
    help: str = Field(default="", max_length=1000)

    @field_validator("key")
    @classmethod
    def no_credentials(cls, value):
        if value in {"token", "key", "password", "secret", "credentials", "credential", "authorization", "api_key", "private_key", "access_key"} or value.endswith(("_password", "_secret", "_token", "_api_key", "_private_key")):
            raise ValueError("Provider credentials belong in the node environment, not public settings.")
        return value


class Diagnostic(BaseModel):
    code: str = Field(max_length=100)
    severity: Literal["info", "warning", "error"] = "info"
    message: str = Field(max_length=2000)
    profile_id: str | None = None


class AgentEdit(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=5000)
    capabilities: list[str] = Field(default_factory=list, max_length=40)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    expected_version: int = Field(ge=1)


class AgentAnnounce(BaseModel):
    protocol_version: int = Field(default=1, ge=1)
    tool_version: str = Field(default="", max_length=120)
    connection: Literal["mcp", "http", "worker"] = "http"
    capabilities: list[str] = Field(default_factory=list, max_length=40)
    limitations: list[str] = Field(default_factory=list, max_length=30)


class IssueCreate(BaseModel):
    severity: Literal["info", "warning", "error"] = "warning"
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=5000)


class HelpCreate(BaseModel):
    capability: str = Field(default="", max_length=100)
    question: str = Field(min_length=1, max_length=10000)
    task_id: str | None = None


class HelpAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=20000)


RuntimeProfile.model_rebuild()
NodeRegister.model_rebuild()


def execution_contract(profile):
    """Public execution metadata frozen for one generation (never command secrets)."""
    return {key: profile.get(key) for key in (
        "id", "kind", "mode", "driver", "protocol_version", "models", "settings_schema", "required_settings", "execution_revision"
    )}


def validate_settings(profile, values, require=False):
    schema = {field["key"]: field for field in profile.get("settings_schema", [])}
    if set(values) - set(schema):
        raise ValueError("This tool does not advertise one or more of those settings.")
    result = {}
    for key, field in schema.items():
        value = values.get(key, field.get("default"))
        if value is None:
            continue
        kind = field["type"]
        if kind == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{field['label']} must be a boolean.")
        if kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field['label']} must be a number.")
            if not math.isfinite(value):
                raise ValueError(f"{field['label']} must be finite.")
            if field.get("minimum") is not None and value < field["minimum"] or field.get("maximum") is not None and value > field["maximum"]:
                raise ValueError(f"{field['label']} is outside the advertised range.")
        if kind in {"text", "choice"} and not isinstance(value, str):
            raise ValueError(f"{field['label']} must be text.")
        if kind == "choice" and value not in field["options"]:
            raise ValueError(f"Choose a supported value for {field['label']}.")
        result[key] = value
    if require:
        for key in profile.get("required_settings", []):
            if key not in schema:
                raise ValueError(f"Command expects an unadvertised setting: {key}.")
            if key not in result or result[key] == "":
                raise ValueError(f"Configure the required setting: {schema[key]['label']} ({key}).")
    return result
