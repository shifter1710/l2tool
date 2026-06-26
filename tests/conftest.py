import pytest

from core import config


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[defaults]",
                'env = "example"',
                "",
                "[grafana]",
                'find_call_dashboard = "https://grafana.example.local/d/example/find-call-in-logs"',
                'org_id = "000"',
                'env = "example"',
                'env_cluster = "example"',
                "",
                "[opensearch]",
                'base_url = "https://dashboards.example.local/app/data-explorer/discover"',
                "",
                "[opensearch.index_patterns]",
                'bff = "bff-example"',
                'myconnect = "myconnect-example"',
                'sip_stack = "sip-stack-example"',
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
