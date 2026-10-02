import asyncio
import hashlib
import logging
import re
import time
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from repopilot.config import Settings
from repopilot.errors import AppError
from repopilot.models import Issue, State

logger = logging.getLogger(__name__)
BODY_LIMIT = 16_000
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}")


def parse_repository(value: str) -> str:
    value = value.strip()
    if value.startswith("https://"):
        try:
            url = urlsplit(value)
        except ValueError as exc:
            raise AppError(
                "invalid_repository", "Use owner/repo or a GitHub repository URL.", 422
            ) from exc
        if url.netloc != "github.com" or url.query or url.fragment:
            raise AppError("invalid_repository", "Use owner/repo or a GitHub repository URL.", 422)
        value = url.path.strip("/")
    else:
        value = value.rstrip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if not REPOSITORY_PATTERN.fullmatch(value) or value.split("/")[-1] in {".", ".."}:
        raise AppError("invalid_repository", "Use owner/repo or a GitHub repository URL.", 422)
    return value


def normalize_issue(data: dict, repository: str) -> Issue:
    try:
        body = data.get("body") or ""
        number = data["number"]
        return Issue(
            number=number,
            title=data["title"],
            body=body[:BODY_LIMIT],
            state=data["state"],
            labels=[label["name"] for label in data.get("labels", [])],
            author=(data.get("user") or {}).get("login", "unknown"),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            comments=data.get("comments", 0),
            html_url=f"https://github.com/{repository}/issues/{number}",
            body_truncated=len(body) > BODY_LIMIT,
            content_hash=hashlib.sha256(body.encode()).hexdigest(),
        )
    except (KeyError, TypeError, AttributeError, ValidationError) as exc:
        raise AppError("github_invalid_response", "GitHub returned unexpected issue data.") from exc


def retry_after(response: httpx.Response) -> int | None:
    seconds = response.headers.get("retry-after")
    if seconds and seconds.isdigit():
        return int(seconds)
    reset = response.headers.get("x-ratelimit-reset")
    if reset and reset.isdigit() and response.headers.get("x-ratelimit-remaining") == "0":
        return max(1, int(reset) - int(time.time()))
    return None


class GitHubClient:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def get(self, path: str, params: dict | None = None) -> object:
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = await self.client.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt < self.settings.max_retries:
                    await asyncio.sleep(0.25 * 2**attempt)
                    continue
                raise AppError(
                    "github_unavailable",
                    "Could not reach GitHub. Check your connection and try again.",
                    503,
                ) from exc
            wait = retry_after(response)
            rate_limited = response.status_code == 429 or (
                response.status_code == 403
                and (wait is not None or response.headers.get("x-ratelimit-remaining") == "0")
            )
            transient = response.status_code in {500, 502, 503, 504} or rate_limited
            if transient and attempt < self.settings.max_retries and (wait is None or wait <= 2):
                logger.warning(
                    "GitHub retry: status=%s attempt=%s", response.status_code, attempt + 1
                )
                await asyncio.sleep(wait if wait is not None else 0.25 * 2**attempt)
                continue
            if rate_limited:
                raise AppError(
                    "github_rate_limit",
                    "GitHub's rate limit was reached. Wait before trying again.",
                    429,
                    wait,
                )
            if response.status_code == 401:
                raise AppError("github_auth", "GitHub rejected the token. Check GITHUB_TOKEN.", 401)
            if response.status_code == 403:
                raise AppError(
                    "github_forbidden",
                    "GitHub denied access. Check the token's repository permissions.",
                    403,
                )
            if response.status_code == 404:
                raise AppError(
                    "github_not_found",
                    "Repository or issue not found. Private repositories need a token.",
                    404,
                )
            if response.status_code >= 400:
                raise AppError("github_error", "GitHub could not complete the request.", 502)
            if response.is_redirect:
                raise AppError(
                    "github_moved",
                    "This repository or issue moved. Use its current GitHub URL.",
                    409,
                )
            try:
                return response.json()
            except ValueError as exc:
                raise AppError("github_invalid_response", "GitHub returned invalid JSON.") from exc
        raise RuntimeError("Unreachable retry state")

    async def list_issues(self, repository: str, state: State, limit: int) -> list[Issue]:
        issues: list[Issue] = []
        for page in range(1, 4):
            data = await self.get(
                f"/repos/{repository}/issues",
                {
                    "state": state,
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": 100,
                    "page": page,
                },
            )
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise AppError(
                    "github_invalid_response", "GitHub returned an unexpected issue list."
                )
            for item in data:
                # GitHub's issues endpoint also returns pull requests.
                if "pull_request" not in item:
                    issues.append(normalize_issue(item, repository))
                    if len(issues) == limit:
                        return issues
            if len(data) < 100:
                break
        return issues

    async def get_issue(self, repository: str, number: int) -> Issue:
        data = await self.get(f"/repos/{repository}/issues/{number}")
        if not isinstance(data, dict):
            raise AppError("github_invalid_response", "GitHub returned unexpected issue data.")
        if "pull_request" in data:
            raise AppError("not_an_issue", "Choose an issue rather than a pull request.", 422)
        return normalize_issue(data, repository)
