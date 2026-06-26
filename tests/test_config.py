from core import config


def test_config_reads_local_config(monkeypatch, tmp_path):
    example_path = tmp_path / "config.example.toml"
    config_path = tmp_path / "config.toml"
    example_path.write_text(
        '\n'.join([
            "[defaults]",
            'env = "example"',
            "",
            "[grafana]",
            'find_call_dashboard = "https://example.local/grafana"',
        ]),
        encoding="utf-8",
    )
    config_path.write_text(
        '\n'.join([
            "[defaults]",
            'env = "local"',
            "",
            "[grafana]",
            'find_call_dashboard = "https://local.test/grafana"',
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config, "EXAMPLE_CONFIG_PATH", example_path)

    assert config.default_env() == "local"
    assert config.grafana_find_call_dashboard() == "https://local.test/grafana"


def test_config_missing_local_file_raises_helpful_error(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing-config.toml")

    try:
        config.load_config()
    except FileNotFoundError as error:
        assert str(error) == (
            "Config file config.toml not found. "
            "Copy config.example.toml to config.toml and fill real values."
        )
    else:
        raise AssertionError("Expected FileNotFoundError")
