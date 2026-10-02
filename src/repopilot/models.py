from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["demo", "live"]
State = Literal["open", "closed", "all"]


class Issue(BaseModel):
    number: int = Field(gt=0)
    title: str
    body: str
    state: Literal["open", "closed"]
    labels: list[str]
    author: str
    created_at: str
    updated_at: str
    comments: int = Field(ge=0)
    html_url: str
    body_truncated: bool = False
    content_hash: str = Field(default="", exclude=True)


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=1800)
    category: Literal["bug", "feature", "question", "documentation", "maintenance"]
    priority: Literal["high", "medium", "low"]
    rationale: str = Field(min_length=1, max_length=1400)
    suggested_labels: list[str] = Field(max_length=5)
    missing_info: list[str] = Field(max_length=6)
    next_steps: list[str] = Field(min_length=1, max_length=6)
    draft_reply: str = Field(min_length=1, max_length=2500)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str = Field(min_length=3, max_length=200)
    issue_number: int = Field(gt=0, le=2**31 - 1)
    mode: Mode = "demo"


class IssueList(BaseModel):
    repository: str
    mode: Mode
    issues: list[Issue]
    notice: str


class AnalysisResult(BaseModel):
    repository: str
    mode: Mode
    issue: Issue
    analysis: Analysis
    provider: Literal["demo", "openai"]
    model: str | None
    cached: bool = False
