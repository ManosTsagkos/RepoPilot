import httpx
import pytest
from fastapi.testclient import TestClient

from repopilot.config import Settings
from repopilot.main import create_app


def no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"An offline endpoint contacted {request.url.host}")


def test_demo_health_config_and_analysis_work_without_credentials_or_network(
    settings: Settings,
) -> None:
    settings = settings.model_copy(update={"openai_api_key": None, "github_token": None})
    with TestClient(create_app(settings, httpx.MockTransport(no_network))) as client:
        health = client.get("/api/health")
        config = client.get("/api/config")
        issues = client.get("/api/issues", params={"state": "all"})
        assert health.status_code == config.status_code == issues.status_code == 200
        assert health.json()["status"] == "ok"
        assert config.json()["llm_configured"] is False
        assert config.json()["github_configured"] is False
        assert issues.json()["repository"] == "repopilot/taskboard"
        assert issues.json()["mode"] == "demo"
        assert len(issues.json()["issues"]) == 6
        assert "pre-written" in issues.json()["notice"]
        for issue in issues.json()["issues"]:
            response = client.post(
                "/api/analyze",
                json={
                    "repository": "repopilot/taskboard",
                    "issue_number": issue["number"],
                    "mode": "demo",
                },
            )
            assert response.status_code == 200
            result = response.json()
            assert result["issue"]["number"] == issue["number"]
            assert result["provider"] == "demo"
            assert result["model"] is None
            assert result["cached"] is False
            assert result["analysis"]["summary"]
            assert result["analysis"]["next_steps"]


def test_demo_state_filter_and_limit_are_respected(settings: Settings) -> None:
    with TestClient(create_app(settings, httpx.MockTransport(no_network))) as client:
        opened = client.get("/api/issues")
        closed = client.get("/api/issues", params={"state": "closed"})
        limited = client.get("/api/issues", params={"state": "all", "limit": 2})

    assert len(opened.json()["issues"]) == 5
    assert all(issue["state"] == "open" for issue in opened.json()["issues"])
    assert len(closed.json()["issues"]) == 1
    assert closed.json()["issues"][0]["state"] == "closed"
    assert len(limited.json()["issues"]) == 2


def test_config_exposes_capabilities_without_revealing_tokens(settings: Settings) -> None:
    with TestClient(create_app(settings, httpx.MockTransport(no_network))) as client:
        response = client.get("/api/config")

    assert response.status_code == 200
    result = response.json()
    assert result["github_configured"] is True
    assert result["llm_configured"] is True
    assert result["model"] == settings.openai_model
    assert "sk-unit-test-only" not in response.text
    assert "ghp-unit-test-only" not in response.text
    assert "openai_api_key" not in result
    assert "github_token" not in result
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "params",
    [
        {"mode": "unknown"},
        {"state": "pending"},
        {"limit": 0},
        {"limit": 31},
        {"limit": "many"},
        {"repository": "https://example.com/acme/taskboard"},
        {"repository": "acme/../secret"},
        {"repository": "https://[github.com/acme/taskboard"},
    ],
)
def test_invalid_issue_queries_are_rejected_without_network(
    settings: Settings, params: dict[str, str | int]
) -> None:
    with TestClient(create_app(settings, httpx.MockTransport(no_network))) as client:
        response = client.get("/api/issues", params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"invalid_request", "invalid_repository"}


@pytest.mark.parametrize(
    "changes",
    [
        {"issue_number": 0},
        {"issue_number": -1},
        {"issue_number": 2**31},
        {"mode": "unknown"},
        {"extra_field": "sk-sensitive-request-content"},
        {"repository": "https://github.com/acme/taskboard?token=sk-sensitive-request-content"},
    ],
)
def test_invalid_analysis_requests_are_rejected_without_echoing_input(
    settings: Settings, changes: dict[str, str | int]
) -> None:
    body = {"repository": "repopilot/taskboard", "issue_number": 241, "mode": "demo", **changes}
    with TestClient(create_app(settings, httpx.MockTransport(no_network))) as client:
        response = client.post("/api/analyze", json=body)

    assert response.status_code == 422
    assert "sk-sensitive-request-content" not in response.text
    assert response.json()["error"]["code"] in {"invalid_request", "invalid_repository"}


def test_unknown_demo_issue_returns_not_found(settings: Settings) -> None:
    with TestClient(create_app(settings, httpx.MockTransport(no_network))) as client:
        response = client.post(
            "/api/analyze",
            json={"repository": "repopilot/taskboard", "issue_number": 9999, "mode": "demo"},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "issue_not_found"


@pytest.mark.parametrize("origin", ["https://unrelated.example", "https://[invalid"])
def test_foreign_or_malformed_origin_cannot_trigger_analysis(
    settings: Settings, origin: str
) -> None:
    with TestClient(create_app(settings, httpx.MockTransport(no_network))) as client:
        response = client.post(
            "/api/analyze",
            json={"repository": "acme/taskboard", "issue_number": 7, "mode": "live"},
            headers={"origin": origin},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_origin"


def test_local_dashboard_origin_can_use_demo_analysis(settings: Settings) -> None:
    with TestClient(create_app(settings, httpx.MockTransport(no_network))) as client:
        response = client.post(
            "/api/analyze",
            json={"repository": "repopilot/taskboard", "issue_number": 241, "mode": "demo"},
            headers={"origin": "http://testserver"},
        )

    assert response.status_code == 200


def test_untrusted_host_is_rejected(settings: Settings) -> None:
    with TestClient(create_app(settings, httpx.MockTransport(no_network))) as client:
        response = client.get("/api/config", headers={"host": "unrelated.example"})

    assert response.status_code == 400
