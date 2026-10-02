import logging
import ssl
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from repopilot import __version__
from repopilot.config import Settings
from repopilot.errors import AppError
from repopilot.github import GitHubClient
from repopilot.llm import LLMClient
from repopilot.models import AnalysisResult, AnalyzeRequest, IssueList, Mode, State
from repopilot.service import DEMO_REPOSITORY, IssueService

STATIC = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        github_headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "RepoPilot/0.1.0",
        }
        if settings.github_token:
            github_headers["Authorization"] = f"Bearer {settings.github_token.get_secret_value()}"
        openai_headers = {}
        if settings.openai_api_key:
            openai_headers["Authorization"] = f"Bearer {settings.openai_api_key.get_secret_value()}"
        # Use the OS trust store, including Windows' installed certificate authorities.
        tls = ssl.create_default_context()
        async with (
            httpx.AsyncClient(
                base_url="https://api.github.com",
                headers=github_headers,
                timeout=settings.request_timeout,
                transport=transport,
                verify=tls,
            ) as github_client,
            httpx.AsyncClient(
                base_url="https://api.openai.com",
                headers=openai_headers,
                timeout=settings.llm_timeout,
                transport=transport,
                verify=tls,
            ) as openai_client,
        ):
            app.state.service = IssueService(
                GitHubClient(github_client, settings),
                LLMClient(openai_client, settings),
                settings,
            )
            yield

    app = FastAPI(title="RepoPilot", version=__version__, lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
    )

    @app.middleware("http")
    async def protect_local_api(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method == "POST" and origin:
            try:
                parsed = urlsplit(origin)
            except ValueError:
                return JSONResponse(
                    {
                        "error": {
                            "code": "invalid_origin",
                            "message": "Use the local dashboard.",
                            "retry_after": None,
                        }
                    },
                    status_code=403,
                )
            if parsed.netloc != request.headers.get("host") or parsed.scheme != request.url.scheme:
                return JSONResponse(
                    {
                        "error": {
                            "code": "invalid_origin",
                            "message": "Use the local dashboard.",
                            "retry_after": None,
                        }
                    },
                    status_code=403,
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path == "/":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
            )
        return response

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        logger.warning("Request failed: code=%s status=%s", exc.code, exc.status_code)
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else {}
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message, "retry_after": exc.retry_after}},
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "Check the repository, mode, issue number, state, and limit.",
                    "retry_after": None,
                }
            },
            status_code=422,
        )

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/config")
    async def config():
        return {
            "github_configured": bool(settings.github_token),
            "llm_configured": bool(settings.openai_api_key),
            "model": settings.openai_model,
            "demo_repository": DEMO_REPOSITORY,
            "version": __version__,
        }

    @app.get("/api/issues", response_model=IssueList)
    async def issues(
        request: Request,
        repository: Annotated[str, Query(min_length=3, max_length=200)] = DEMO_REPOSITORY,
        state: State = "open",
        limit: Annotated[int, Query(ge=1, le=30)] = 30,
        mode: Mode = "demo",
    ):
        return await request.app.state.service.list_issues(repository, state, limit, mode)

    @app.post("/api/analyze", response_model=AnalysisResult)
    async def analyze(request: Request, body: AnalyzeRequest):
        return await request.app.state.service.analyze(
            body.repository,
            body.issue_number,
            body.mode,
        )

    @app.get("/", include_in_schema=False)
    async def dashboard():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
