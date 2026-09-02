import json
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from core import config
from modules import recording_mgw


def configure_recording(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[services.zapis]
url = "https://grafana.test/d/calls?orgId=42"

[grafana.recording]
loki_datasource_uid = "loki-test"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)


def test_secondary_recording_search_uses_validated_uuid_and_ticket_time(
    monkeypatch,
    tmp_path,
):
    configure_recording(monkeypatch, tmp_path)
    call_uuid = "12345678-1234-5678-1234-567812345678"

    url = recording_mgw.build(
        {
            "call_uuid": call_uuid,
            "event_time": datetime(2026, 9, 1, 12, 0),
            "event_datetimes": [datetime(2026, 9, 1, 12, 0)],
            "tz": "Europe/Moscow",
            "window": 30,
        }
    )[0]
    pane = json.loads(parse_qs(urlsplit(url).query)["panes"][0])["A"]

    assert pane["range"] == {
        "from": "2026-09-01T08:30:00.000Z",
        "to": "2026-09-01T09:30:00.000Z",
    }
    assert call_uuid in pane["queries"][0]["expr"]


def test_secondary_recording_search_rejects_invalid_uuid():
    with pytest.raises(ValueError, match="Некорректный UUID звонка"):
        recording_mgw.build({"call_uuid": 'broken" |~ ".*"'})
