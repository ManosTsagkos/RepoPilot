import httpx
import pytest
from fastapi.testclient import TestClient

from repopilot.config import Settings
from repopilot.main import create_app


@pytest.mark.parametrize("issue_number", [True, 7.0, "7"])
def test_analysis_requires_a_json_integer_before_contacting_upstream_apis(
    settings: Settings, issue_number: object
) -> None:
    def unexpected_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Invalid issue numbers must not contact external APIs")

    with TestClient(create_app(settings, httpx.MockTransport(unexpected_request))) as client:
        response = client.post(
            "/api/analyze",
            json={"repository": "acme/taskboard", "issue_number": issue_number, "mode": "live"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
