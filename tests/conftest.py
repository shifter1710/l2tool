import pytest

from core import config, dynamic_sources, runbook


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[services.zapis]",
                'url = "https://grafana.example.local/d/example/find-call-in-logs?orgId=000&var-env=example&var-env_cluster=example"',
                "",
                "[services.sip_stack]",
                'url = "https://dashboards.example.local/app/data-explorer/discover#?_a=(metadata:(indexPattern:sip-stack-example,view:discover))"',
                "",
                "[services.bff]",
                'url = "https://dashboards.example.local/app/data-explorer/discover#?_a=(metadata:(indexPattern:bff-example,view:discover))"',
                "",
                "[services.myconnect]",
                'url = "https://dashboards.example.local/app/data-explorer/discover#?_a=(metadata:(indexPattern:myconnect-example,view:discover))"',
                "",
                "[services.myconnect_call]",
                'url = "https://dashboards.example.local/app/data-explorer/discover#?_a=(metadata:(indexPattern:myconnect-example,view:discover))"',
                "",
                "[grafana.recording]",
                'loki_datasource_uid = "loki-example"',
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(dynamic_sources, "STORE_PATH", tmp_path / "diagnostic_sources.json")
    monkeypatch.setattr(runbook, "STORE_PATH", tmp_path / "runbook.json")
