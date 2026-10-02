"""Offline fixtures: every upstream response is controlled by a test."""

from collections.abc import Callable
from typing import Any

import pytest

from repopilot.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        openai_api_key="sk-unit-test-only",
        github_token="ghp-unit-test-only",
        max_retries=0,
        _env_file=None,
    )


@pytest.fixture
def issue_payload() -> Callable[..., dict[str, Any]]:
    def make_issue(number: int = 7, **changes: Any) -> dict[str, Any]:
        issue = {
            "id": 1000 + number,
            "number": number,
            "title": "Uploads fail after a connection interruption",
            "body": "The upload stops at 50%. Expected the upload to resume after reconnecting.",
            "state": "open",
            "labels": [{"name": "bug"}],
            "user": {"login": "reporter"},
            "created_at": "2026-09-01T10:00:00Z",
            "updated_at": "2026-09-02T10:00:00Z",
            "comments": 2,
            "html_url": f"https://github.com/acme/taskboard/issues/{number}",
        }
        issue.update(changes)
        return issue

    return make_issue


@pytest.fixture
def analysis_payload() -> dict[str, Any]:
    return {
        "summary": "A reporter says an interrupted upload does not resume.",
        "category": "bug",
        "priority": "medium",
        "rationale": "The report blocks uploads but does not describe data loss.",
        "suggested_labels": ["bug", "uploads"],
        "missing_info": ["Application version", "Steps to reproduce"],
        "next_steps": ["Reproduce an upload while disconnecting the network."],
        "draft_reply": "Thanks for reporting this. Which version are you using?",
    }
