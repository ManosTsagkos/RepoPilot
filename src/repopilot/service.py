import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from pathlib import Path

from repopilot.config import Settings
from repopilot.errors import AppError
from repopilot.github import GitHubClient, normalize_issue, parse_repository
from repopilot.llm import LLMClient
from repopilot.models import Analysis, AnalysisResult, IssueList, Mode, State

DEMO_REPOSITORY = "repopilot/taskboard"


class IssueService:
    def __init__(self, github: GitHubClient, llm: LLMClient, settings: Settings) -> None:
        self.github = github
        self.llm = llm
        self.settings = settings
        samples = json.loads((Path(__file__).parent / "data" / "demo.json").read_text("utf-8"))
        self.demo = {
            item["issue"]["number"]: (
                normalize_issue(item["issue"], DEMO_REPOSITORY),
                Analysis.model_validate(item["analysis"]),
            )
            for item in samples
        }
        self.cache: OrderedDict[str, tuple[float, AnalysisResult]] = OrderedDict()
        self.analysis_lock = asyncio.Lock()

    async def list_issues(
        self,
        repository: str,
        state: State,
        limit: int,
        mode: Mode,
    ) -> IssueList:
        repository = parse_repository(repository)
        if mode == "demo":
            issues = [issue for issue, _ in self.demo.values()]
            if state != "all":
                issues = [issue for issue in issues if issue.state == state]
            return IssueList(
                repository=DEMO_REPOSITORY,
                mode=mode,
                issues=issues[:limit],
                notice="Sample issues and pre-written analyses. "
                "Demo mode makes no external API calls.",
            )
        issues = await self.github.list_issues(repository, state, limit)
        return IssueList(
            repository=repository,
            mode=mode,
            issues=issues,
            notice="Latest matching issues, up to the requested limit. Pull requests are excluded; "
            "at most 300 GitHub entries are scanned. This is not a complete repository audit.",
        )

    async def analyze(self, repository: str, number: int, mode: Mode) -> AnalysisResult:
        repository = parse_repository(repository)
        if mode == "demo":
            if number not in self.demo:
                raise AppError("issue_not_found", "This issue is not in the demo dataset.", 404)
            issue, analysis = self.demo[number]
            return AnalysisResult(
                repository=DEMO_REPOSITORY,
                mode=mode,
                issue=issue,
                analysis=analysis,
                provider="demo",
                model=None,
            )
        if not self.settings.openai_api_key:
            raise AppError(
                "llm_not_configured",
                "Add OPENAI_API_KEY to .env and restart to use live analysis.",
                503,
            )
        issue = await self.github.get_issue(repository, number)
        signature = json.dumps(
            [
                repository.lower(),
                issue.model_dump(),
                issue.content_hash,
                self.settings.openai_model,
            ],
            sort_keys=True,
        )
        key = hashlib.sha256(signature.encode()).hexdigest()
        try:
            await asyncio.wait_for(self.analysis_lock.acquire(), timeout=1)
        except TimeoutError as exc:
            raise AppError(
                "analysis_busy",
                "Another analysis is running. Try again in a moment.",
                429,
                2,
            ) from exc
        try:
            cached = self.cache.get(key)
            if cached and cached[0] > time.monotonic():
                self.cache.move_to_end(key)
                return cached[1].model_copy(update={"cached": True})
            analysis = await self.llm.analyze(repository, issue)
            result = AnalysisResult(
                repository=repository,
                mode=mode,
                issue=issue,
                analysis=analysis,
                provider="openai",
                model=self.settings.openai_model,
            )
            self.cache[key] = (time.monotonic() + self.settings.cache_ttl, result)
            self.cache.move_to_end(key)
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            return result
        finally:
            self.analysis_lock.release()
