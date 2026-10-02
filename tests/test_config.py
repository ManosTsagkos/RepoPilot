import pytest
from pydantic import ValidationError

from repopilot.config import Settings


def test_pasted_model_names_are_trimmed_before_requests_are_sent():
    config = Settings(openai_model="  gpt-4.1-mini\n", _env_file=None)
    assert config.openai_model == "gpt-4.1-mini"


def test_whitespace_model_name_is_rejected_at_startup():
    with pytest.raises(ValidationError):
        Settings(openai_model=" \t ", _env_file=None)


def test_empty_credentials_disable_live_capabilities():
    config = Settings(openai_api_key=" \n", github_token="\t", _env_file=None)
    assert config.openai_api_key is None
    assert config.github_token is None


def test_environment_takes_precedence_over_dotenv_without_exposing_secrets(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENAI_API_KEY=dotenv-secret\nOPENAI_MODEL=gpt-4.1-mini\n", "utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    config = Settings(_env_file=dotenv)
    assert config.openai_api_key.get_secret_value() == "environment-secret"
    assert "environment-secret" not in repr(config)
    assert "dotenv-secret" not in repr(config)
