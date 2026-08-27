import pytest

from core import config
from modules import bff_logs_opensearch, find_call_in_logs
from services.opensearch import extract_index_pattern, resolve_target
from services.registry import SERVICES


def test_service_registry_separates_platforms_and_modules():
    assert list(SERVICES) == [
        "zapis",
        "sip_stack",
        "bff",
        "myconnect",
        "myconnect_call",
    ]
    assert SERVICES["zapis"].platform == "grafana"
    assert SERVICES["bff"].platform == "opensearch"
    assert callable(SERVICES["bff"].module.build)


def test_extract_index_pattern_from_encoded_copied_url():
    url = (
        "https://opensearch.test/discover#?"
        "_a=%28metadata%3A%28indexPattern%3A%27bff-view-id%27%29%29"
    )

    assert extract_index_pattern(url) == "bff-view-id"


def test_opensearch_target_keeps_query_before_fragment(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[services.bff]
url = "https://opensearch.test/discover?security_tenant=private#?_a=(metadata:(indexPattern:bff-view))"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    target = resolve_target("bff", "bff")

    assert target.base_url == (
        "https://opensearch.test/discover?security_tenant=private"
    )
    assert target.index_pattern == "bff-view"


def test_opensearch_link_uses_service_specific_copied_url(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[services.bff]
url = "https://new-opensearch.test/discover#?_a=(metadata:(indexPattern:new-bff-view))"

[opensearch]
base_url = "https://legacy.test/discover"

[opensearch.index_patterns]
bff = "legacy-bff-view"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    url = bff_logs_opensearch.build({"msisdn": "79990000000"})[0]

    assert url.startswith("https://new-opensearch.test/discover#")
    assert "indexPattern:new-bff-view" in url
    assert "legacy-bff-view" not in url


def test_legacy_opensearch_config_still_builds_links(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[opensearch]
base_url = "https://legacy.test/discover"

[opensearch.index_patterns]
bff = "legacy-bff-view"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    url = bff_logs_opensearch.build({"msisdn": "79990000000"})[0]

    assert url.startswith("https://legacy.test/discover#")
    assert "indexPattern:legacy-bff-view" in url


def test_legacy_grafana_config_still_builds_links(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[defaults]
env = "legacy"

[grafana]
find_call_dashboard = "https://legacy-grafana.test/dashboard"
org_id = "42"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    url = find_call_in_logs.build({"msisdn": "79990000000"})[0]

    assert url.startswith("https://legacy-grafana.test/dashboard?")
    assert "orgId=42" in url
    assert "var-env=legacy" in url


def test_opensearch_url_without_data_view_has_helpful_error(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[services.bff]
url = "https://opensearch.test/discover"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    with pytest.raises(ValueError, match="Copy a Discover URL"):
        resolve_target("bff", "bff")
