import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from repopilot.config import Settings
from repopilot.main import create_app

REPOSITORY = "acme/taskboard"


def test_live_list_excludes_pull_requests_and_fetches_another_page(
    settings: Settings, issue_payload: Callable[..., dict[str, Any]]
) -> None:
    requests = []
    first_page = [issue_payload(1)] + [
        issue_payload(number, pull_request={"url": "https://api.github.com/pulls/1"})
        for number in range(2, 101)
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "api.github.com"
        assert request.url.path == "/repos/acme/taskboard/issues"
        assert request.headers["authorization"] == "Bearer ghp-unit-test-only"
        assert request.url.params["state"] == "closed"
        assert request.url.params["per_page"] == "100"
        if request.url.params["page"] == "1":
            return httpx.Response(200, json=first_page)
        assert request.url.params["page"] == "2"
        return httpx.Response(
            200, json=[issue_payload(101, state="closed"), issue_payload(102, state="closed")]
        )

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.get(
            "/api/issues",
            params={"repository": REPOSITORY, "state": "closed", "limit": 3, "mode": "live"},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["repository"] == REPOSITORY
    assert result["mode"] == "live"
    assert [issue["number"] for issue in result["issues"]] == [1, 101, 102]
    assert len(requests) == 2


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "code"),
    [
        (401, 401, "github_auth"),
        (403, 403, "github_forbidden"),
        (404, 404, "github_not_found"),
        (429, 429, "github_rate_limit"),
        (500, 502, "github_error"),
    ],
)
def test_github_errors_have_actionable_sanitized_envelopes(
    settings: Settings, upstream_status: int, expected_status: int, code: str
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            upstream_status,
            json={"message": "provider secret: sk-do-not-expose"},
        )

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.get("/api/issues", params={"repository": REPOSITORY, "mode": "live"})

    assert response.status_code == expected_status
    error = response.json()["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert error["retry_after"] is None
    assert "sk-do-not-expose" not in response.text


def test_long_rate_limit_returns_retry_information_without_waiting(settings: Settings) -> None:
    settings = settings.model_copy(update={"max_retries": 2})
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            403,
            headers={"retry-after": "61", "x-ratelimit-remaining": "0"},
            json={"message": "rate limit exceeded"},
        )

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.get("/api/issues", params={"repository": REPOSITORY, "mode": "live"})

    assert response.status_code == 429
    assert response.json()["error"]["retry_after"] == 61
    assert len(requests) == 1


def test_transient_github_failure_is_retried_and_recovers(
    settings: Settings, issue_payload: Callable[..., dict[str, Any]]
) -> None:
    settings = settings.model_copy(update={"max_retries": 1})
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={"message": "temporarily unavailable"})
        return httpx.Response(200, json=[issue_payload()])

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.get("/api/issues", params={"repository": REPOSITORY, "mode": "live"})

    assert response.status_code == 200
    assert response.json()["issues"][0]["number"] == 7
    assert len(requests) == 2


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ProxyError]
)
def test_github_network_failures_are_reported_as_unavailable(
    settings: Settings, failure: type[httpx.RequestError]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise failure("Sensitive connection details", request=request)

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.get("/api/issues", params={"repository": REPOSITORY, "mode": "live"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "github_unavailable"
    assert "Sensitive connection details" not in response.text


@pytest.mark.parametrize("payload", [{"message": "not an issue list"}, [None]])
def test_malformed_github_lists_return_a_controlled_error(settings: Settings, payload: Any) -> None:
    with TestClient(
        create_app(settings, httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    ) as client:
        response = client.get("/api/issues", params={"repository": REPOSITORY, "mode": "live"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "github_invalid_response"


def test_redirects_are_reported_without_following_another_host(settings: Settings) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(301, headers={"location": "https://example.com/private"})

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.get("/api/issues", params={"repository": REPOSITORY, "mode": "live"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "github_moved"
    assert len(requests) == 1


def test_analysis_rejects_pull_requests_before_calling_the_llm(
    settings: Settings, issue_payload: Callable[..., dict[str, Any]]
) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.github.com"
        return httpx.Response(200, json=issue_payload(pull_request={"url": "irrelevant"}))

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.post(
            "/api/analyze",
            json={"repository": REPOSITORY, "issue_number": 7, "mode": "live"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_an_issue"
    assert len(requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"body": False},
        {"body": 0},
        {"body": []},
        {"body": {}},
        {"number": True},
        {"number": "7"},
        {"number": 7.0},
        {"comments": False},
        {"body": "\ud800"},
        {"title": "\ud800"},
        {"labels": [{"name": "\ud800"}]},
        {"user": {"login": "\ud800"}},
    ],
)
def test_malformed_issue_fields_are_rejected_before_rendering_or_analysis(
    settings: Settings,
    issue_payload: Callable[..., dict[str, Any]],
    changes: dict[str, Any],
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        # Escape Unicode to exercise invalid strings received inside valid JSON.
        issue = issue_payload()
        issue.update(changes)
        return httpx.Response(200, content=json.dumps([issue]).encode("utf-8"))

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.get("/api/issues", params={"repository": REPOSITORY, "mode": "live"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "github_invalid_response"


def test_null_body_and_user_are_normalized_without_trusting_external_links(
    settings: Settings, issue_payload: Callable[..., dict[str, Any]]
) -> None:
    issue = issue_payload(body=None, user=None, html_url="https://unrelated.example/unsafe")
    with TestClient(
        create_app(settings, httpx.MockTransport(lambda _: httpx.Response(200, json=[issue])))
    ) as client:
        response = client.get("/api/issues", params={"repository": REPOSITORY, "mode": "live"})

    assert response.status_code == 200
    returned = response.json()["issues"][0]
    assert returned["body"] == ""
    assert returned["author"] == "unknown"
    assert returned["html_url"] == "https://github.com/acme/taskboard/issues/7"


def test_wrong_issue_number_is_rejected_before_a_paid_analysis(
    settings: Settings, issue_payload: Callable[..., dict[str, Any]]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        return httpx.Response(200, json=issue_payload(8))

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.post(
            "/api/analyze",
            json={"repository": REPOSITORY, "issue_number": 7, "mode": "live"},
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "github_invalid_response"


@pytest.mark.parametrize(
    ("header_name", "header_value"),
    [
        (b"retry-after", b"\xb2"),
        (b"x-ratelimit-reset", b"\xb2"),
        (b"retry-after", b"9" * 5000),
        (b"x-ratelimit-reset", b"9" * 5000),
    ],
)
def test_malformed_rate_limit_headers_do_not_crash_the_error_response(
    settings: Settings, header_name: bytes, header_value: bytes
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, headers=[(b"x-ratelimit-remaining", b"0"), (header_name, header_value)]
        )

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.get("/api/issues", params={"repository": REPOSITORY, "mode": "live"})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "github_rate_limit"
    assert response.json()["error"]["retry_after"] is None


def test_corrupt_github_content_encoding_returns_a_controlled_error(settings: Settings) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, headers={"content-encoding": "gzip"}, content=b"corrupt gzip")

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.get("/api/issues", params={"repository": REPOSITORY, "mode": "live"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "github_invalid_response"
    assert len(calls) == 1


def test_public_repository_loading_uses_no_authorization_without_a_github_token(
    settings: Settings, issue_payload: Callable[..., dict[str, Any]]
) -> None:
    settings = settings.model_copy(update={"github_token": None})

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        assert "authorization" not in request.headers
        assert "sk-unit-test-only" not in str(request.headers)
        return httpx.Response(200, json=[issue_payload()])

    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.get("/api/issues", params={"repository": REPOSITORY, "mode": "live"})

    assert response.status_code == 200
