import json
from datetime import date, datetime

from core.case_export import build_case_dict, write_case_json


def test_build_case_dict_exports_structured_context_without_raw_values():
    ctx = {
        "msisdn": "79991234567",
        "msisdn_raw": "+7 (999) 123-45-67",
        "phone_a": "74232253015",
        "phone_a_raw": "8 (423) 225-30-15",
        "phone_b": "73912777454",
        "phone_b_raw": "8 (391) 277-74-54",
        "event_date": date(2026, 5, 4),
        "event_time": datetime(2026, 5, 4, 10, 49),
        "event_datetimes": [
            datetime(2026, 5, 4, 10, 49),
            datetime(2026, 5, 4, 11, 1),
        ],
        "tz": "Europe/Moscow",
        "window": 120,
        "region": "Москва",
    }

    result = build_case_dict(
        ctx,
        ["zapis", "sip_stack", "bff"],
        {"zapis": ["https://example.test/one"], "bff": ["https://example.test/two"]},
        product="recording",
        file_name="current.txt",
    )

    assert result == {
        "schema_version": 1,
        "case_type": "unknown",
        "product": "recording",
        "identifiers": {
            "msisdn": "79991234567",
            "phone_a": "74232253015",
            "phone_b": "73912777454",
        },
        "event": {
            "timezone": "Europe/Moscow",
            "date": "2026-05-04",
            "time": "2026-05-04T10:49:00+03:00",
            "datetimes": [
                "2026-05-04T10:49:00+03:00",
                "2026-05-04T11:01:00+03:00",
            ],
            "window_minutes": 120,
        },
        "location": {
            "region": "Москва",
        },
        "search": {
            "selected_modules": ["zapis", "sip_stack", "bff"],
            "links_by_module": {
                "zapis": ["https://example.test/one"],
                "bff": ["https://example.test/two"],
            },
        },
        "source": {
            "tool": "l2tool",
            "file_name": "current.txt",
        },
    }

    dumped = json.dumps(result, ensure_ascii=False)
    assert "raw" not in dumped
    assert "+7 (999) 123-45-67" not in dumped


def test_build_case_dict_preserves_aware_datetime_offset_without_conversion():
    ctx = {
        "event_date": date(2026, 5, 4),
        "event_time": datetime.fromisoformat("2026-05-04T10:49:00+05:00"),
        "event_datetimes": [datetime.fromisoformat("2026-05-04T10:49:00+05:00")],
        "tz": "Europe/Moscow",
        "window": 60,
    }

    result = build_case_dict(
        ctx,
        ["bff"],
        {},
        product=None,
        file_name="ticket.txt",
    )

    assert result["event"]["time"] == "2026-05-04T10:49:00+05:00"
    assert result["event"]["datetimes"] == ["2026-05-04T10:49:00+05:00"]


def test_write_case_json_creates_parent_and_writes_utf8_pretty_json(tmp_path):
    output_path = tmp_path / "nested" / "case.json"
    data = {"schema_version": 1, "location": {"region": "Москва"}}

    result_path = write_case_json(output_path, data)

    assert result_path == output_path
    raw = output_path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert "  " in raw
    assert "Москва" in raw
    assert json.loads(raw) == data
