import pytest

from repopilot.errors import AppError
from repopilot.github import parse_repository


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("acme/taskboard", "acme/taskboard"),
        (" acme/taskboard ", "acme/taskboard"),
        ("https://github.com/acme/taskboard", "acme/taskboard"),
        ("https://github.com/acme/taskboard/", "acme/taskboard"),
        ("https://github.com/acme/taskboard.git", "acme/taskboard"),
    ],
)
def test_repository_input_normalizes_to_owner_and_name(value: str, expected: str) -> None:
    assert parse_repository(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "../taskboard",
        "acme/..",
        "acme/taskboard/issues",
        "https://example.com/acme/taskboard",
        "https://github.com.evil.example/acme/taskboard",
        "https://user:password@github.com/acme/taskboard",
        "https://github.com/acme/taskboard?token=private",
        "https://github.com/acme/taskboard#issues",
        "https://github.com/acme/taskboard/../../secrets",
        "http://github.com/acme/taskboard",
        "https://github.com/acme/%2e%2e",
        "https://github.com:443/acme/taskboard",
        "https://[github.com/acme/taskboard",
        "https://github.com\uff0facme/taskboard",
    ],
)
def test_repository_input_rejects_noncanonical_or_unsafe_targets(value: str) -> None:
    with pytest.raises(AppError) as caught:
        parse_repository(value)
    assert caught.value.code == "invalid_repository"
    assert caught.value.status_code == 422
