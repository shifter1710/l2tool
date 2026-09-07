from pathlib import Path
from urllib.parse import quote

import pytest

from core.url_guard import (
    find_config_issues,
    find_text_secrets,
    find_url_secrets,
    is_sensitive_name,
    validate_external_url,
)

ROOT_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("secretary_numbers", False),  # «secretary», а не «secret»
        ("key", False),  # ключ продукта — слишком общий
        ("keywords", False),
        ("index_pattern", False),
        ("minutes_before", False),
        ("access_token", True),
        ("token", True),
        ("private_token", True),
        ("password", True),
        ("passwd", True),
        ("X-Auth-Token", True),
        ("x-api-key", True),
        ("apiKey", True),
        ("authorization", True),
    ],
)
def test_is_sensitive_name(name, expected):
    assert is_sensitive_name(name) is expected


def test_example_configs_are_clean():
    # Эталонный конфиг не должен давать ложных срабатываний
    example = (ROOT_DIR / "config.example.toml").read_text(encoding="utf-8")
    assert find_config_issues(example) == []


def test_find_text_secrets_catches_toml_keys_with_spaces():
    text = "\n".join(
        [
            "[services.zapis]",
            'url = "https://grafana.example.local/d/x?orgId=1"',
            'token = "abc"',  # TOML-стиль «ключ = значение» с пробелами
            'password = "hunter2"',
            'grafana.authorization = "Bearer x"',
        ]
    )
    findings = find_text_secrets(text)
    assert len(findings) == 3
    assert any("«token»" in item for item in findings)
    assert any("«password»" in item for item in findings)
    assert any("«grafana.authorization»" in item for item in findings)


def test_find_text_secrets_catches_url_credentials_and_params():
    findings = find_text_secrets('url = "https://user:pass@grafana.example.local/d/x?orgId=1"')
    assert any("логин/пароль" in item for item in findings)

    findings = find_text_secrets('url = "https://grafana.example.local/d/x?private_token=abc"')
    assert any("private_token" in item for item in findings)


def test_find_url_secrets_scans_encoded_state():
    state = quote('{"apiKey":"abc"}')
    url = f"https://grafana.example.local/explore?panes={state}&orgId=1"
    assert any("apiKey" in item for item in find_url_secrets(url))


def test_find_config_issues_rejects_non_http_schemes():
    issues = find_config_issues('url = "javascript:alert(1)"')
    assert any("javascript" in item for item in issues)
    assert find_config_issues('url = "data:text/html,x"')
    assert find_config_issues('url = "ftp://files.example.local/x"')


def test_find_config_issues_clean_config_passes():
    text = "\n".join(
        [
            "[services.zapis]",
            'url = "https://grafana.example.local/d/x?orgId=1&var-env=prod"',
            "[call_history]",
            "secretary_numbers = []",
            'default_open = "zapis"',
            "max_calls = 7",
        ]
    )
    assert find_config_issues(text) == []


def test_validate_external_url():
    assert validate_external_url("") == ""
    assert validate_external_url(None) is None
    assert validate_external_url("http://example.local/d") == "http://example.local/d"
    with pytest.raises(ValueError, match="http:// или https://"):
        validate_external_url("javascript:alert(1)")
    with pytest.raises(ValueError, match="http:// или https://"):
        validate_external_url("file:///etc/passwd")
    with pytest.raises(ValueError, match="логин и пароль"):
        validate_external_url("https://user:pass@example.local/")
