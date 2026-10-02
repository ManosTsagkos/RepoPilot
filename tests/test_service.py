import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from repopilot.config import Settings
from repopilot.errors import AppError
from repopilot.github import normalize_issue
from repopilot.models import Analysis, Issue
from repopilot.service import IssueService

REPOSITORY = "acme/taskboard"


class StubGitHub:
    def __init__(self, make_issue: Callable[..., dict[str, Any]]) -> None:
        self.make_issue = make_issue

    async def get_issue(self, repository: str, number: int) -> Issue:
        return normalize_issue(self.make_issue(number), repository)


class ControlledModel:
    def __init__(self, analysis: dict[str, Any]) -> None:
        self.result = Analysis.model_validate(analysis)
        self.calls = 0
        self.blocked_number: int | None = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.fail_next = False

    async def analyze(self, repository: str, issue: Issue) -> Analysis:
        self.calls += 1
        if issue.number == self.blocked_number:
            self.started.set()
            await self.release.wait()
        if self.fail_next:
            self.fail_next = False
            raise AppError("llm_invalid_response", "Invalid analysis")
        return self.result


def test_cached_analysis_remains_available_while_another_model_request_is_running(
    settings: Settings,
    issue_payload: Callable[..., dict[str, Any]],
    analysis_payload: dict[str, Any],
) -> None:
    async def scenario():
        model = ControlledModel(analysis_payload)
        service = IssueService(StubGitHub(issue_payload), model, settings)
        await service.analyze(REPOSITORY, 7, "live")
        model.blocked_number = 8
        running = asyncio.create_task(service.analyze(REPOSITORY, 8, "live"))
        await model.started.wait()
        try:
            cached = await asyncio.wait_for(service.analyze(REPOSITORY, 7, "live"), timeout=0.2)
            assert cached.cached is True
            assert cached.issue.number == 7
            assert model.calls == 2
        finally:
            model.release.set()
            await running

    asyncio.run(scenario())


def test_concurrent_requests_for_one_issue_do_not_duplicate_the_paid_call(
    settings: Settings,
    issue_payload: Callable[..., dict[str, Any]],
    analysis_payload: dict[str, Any],
) -> None:
    async def scenario():
        model = ControlledModel(analysis_payload)
        model.blocked_number = 7
        service = IssueService(StubGitHub(issue_payload), model, settings)
        first = asyncio.create_task(service.analyze(REPOSITORY, 7, "live"))
        await model.started.wait()
        second = asyncio.create_task(service.analyze(REPOSITORY, 7, "live"))
        await asyncio.sleep(0)
        model.release.set()
        results = await asyncio.gather(first, second)
        assert model.calls == 1
        assert [result.cached for result in results] == [False, True]

    asyncio.run(scenario())


def test_model_failure_releases_the_lock_and_does_not_cache_the_failure(
    settings: Settings,
    issue_payload: Callable[..., dict[str, Any]],
    analysis_payload: dict[str, Any],
) -> None:
    async def scenario():
        model = ControlledModel(analysis_payload)
        model.fail_next = True
        service = IssueService(StubGitHub(issue_payload), model, settings)
        with pytest.raises(AppError, match="Invalid analysis"):
            await service.analyze(REPOSITORY, 7, "live")
        assert not service.analysis_lock.locked()
        assert not service.cache
        result = await service.analyze(REPOSITORY, 7, "live")
        assert result.cached is False
        assert model.calls == 2

    asyncio.run(scenario())


def test_cancelled_analysis_releases_the_lock_without_storing_partial_output(
    settings: Settings,
    issue_payload: Callable[..., dict[str, Any]],
    analysis_payload: dict[str, Any],
) -> None:
    async def scenario():
        model = ControlledModel(analysis_payload)
        model.blocked_number = 7
        service = IssueService(StubGitHub(issue_payload), model, settings)
        task = asyncio.create_task(service.analyze(REPOSITORY, 7, "live"))
        await model.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not service.analysis_lock.locked()
        assert not service.cache
        model.blocked_number = None
        assert (await service.analyze(REPOSITORY, 7, "live")).cached is False

    asyncio.run(scenario())


def test_cache_is_bounded_and_recently_used_results_survive_eviction(
    settings: Settings,
    issue_payload: Callable[..., dict[str, Any]],
    analysis_payload: dict[str, Any],
) -> None:
    async def scenario():
        model = ControlledModel(analysis_payload)
        service = IssueService(StubGitHub(issue_payload), model, settings)
        for number in range(1, 129):
            await service.analyze(REPOSITORY, number, "live")
        assert (await service.analyze(REPOSITORY, 1, "live")).cached is True
        await service.analyze(REPOSITORY, 129, "live")
        assert len(service.cache) == 128
        assert (await service.analyze(REPOSITORY, 1, "live")).cached is True
        assert (await service.analyze(REPOSITORY, 2, "live")).cached is False
        assert model.calls == 130

    asyncio.run(scenario())


def test_disabled_cache_does_not_retain_issue_content(
    settings: Settings,
    issue_payload: Callable[..., dict[str, Any]],
    analysis_payload: dict[str, Any],
) -> None:
    async def scenario():
        model = ControlledModel(analysis_payload)
        service = IssueService(
            StubGitHub(issue_payload), model, settings.model_copy(update={"cache_ttl": 0})
        )
        for _ in range(2):
            assert (await service.analyze(REPOSITORY, 7, "live")).cached is False
        assert not service.cache
        assert model.calls == 2

    asyncio.run(scenario())
