"""Task pack and task instance schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MutationSpec(BaseModel):
    type: str
    path: str | None = None
    key: str | None = None
    value: Any = None
    file: str | None = None
    template: str | None = None
    content: str | None = None
    sql: str | None = None
    service: str | None = None
    patch: str | None = None
    find: str | None = None
    replace: str | None = None


class VerifierSpec(BaseModel):
    success_requires: dict[str, Any] = Field(default_factory=dict)
    partial_credit: list[dict[str, Any]] = Field(default_factory=list)


class TaskTools(BaseModel):
    allow: list[str] = Field(
        default_factory=lambda: [
            "files.*",
            "http.*",
            "logs.*",
            "services.*",
            "db.query",
            "db.exec",
            "shell.exec",
            "tests.run",
            "submit.done",
        ]
    )


class TaskBriefSpec(BaseModel):
    title: str
    description: str
    public_success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)


class TaskSpec(BaseModel):
    id: str
    family: str
    tier: str = "L1"
    scenario: str = "shopstack"
    seed_policy: str = "required"
    tools: TaskTools = Field(default_factory=TaskTools)
    brief: TaskBriefSpec
    mutations: list[MutationSpec] = Field(default_factory=list)
    verifiers: VerifierSpec = Field(default_factory=VerifierSpec)
    metadata: dict[str, Any] = Field(default_factory=dict)
    budgets: dict[str, Any] = Field(default_factory=dict)


class TaskDocument(BaseModel):
    api_version: str = "cascade/v1"
    task: TaskSpec


class PackInfo(BaseModel):
    id: str
    name: str
    version: str = "0.1.0"
    min_runtime_version: str = "0.1.0"
    schema_version: int = 1
    license: str = "Apache-2.0"
    scenario: str = "shopstack"
    default_budgets: dict[str, Any] = Field(default_factory=dict)
    splits: dict[str, Any] = Field(default_factory=dict)


class PackManifest(BaseModel):
    api_version: str = "cascade/v1"
    pack: PackInfo
