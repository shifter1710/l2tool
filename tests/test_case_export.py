import json
from datetime import date, datetime

from core.case_export import build_case_dict, case_summary_fields
from core.utils import hash_phone


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
            "phone_a_values": [],
            "phone_b": "73912777454",
            "phone_b_values": [],
            "call_uuid": "",
        },
        "event": {
            "timezone": "Europe/Moscow",
            "date": "2026-05-04",
            "time": "2026-05-04T10:49:00+03:00",
            "datetimes": [
                "2026-05-04T10:49:00+03:00",
                "2026-05-04T11:01:00+03:00",
            ],
            "time_range": [],
            "window_minutes": 120,
        },
        "interpretation": {
            "problem_scope": None,
            "event_date_source": None,
            "phone_a_partial": False,
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
            "submitted_at_msk": None,
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


def test_case_summary_fields_covers_real_context_fields():
    ctx = {
        "msisdn": "79991234567",
        "phone_a_values": ["79991234567", "79211234567"],
        "phone_a_partial": False,
        "phone_b_values": ["73912777454"],
        "event_time": datetime(2026, 5, 4, 10, 49),
        "region": "Москва",
        "tz": "Europe/Moscow",
        "submitted_at": datetime(2026, 5, 4, 9, 12, 30),
        "call_uuid": "12345678-1234-5678-1234-567812345678",
        "window": 120,
    }

    fields = case_summary_fields(ctx, "recording")

    assert fields == [
        ("Номер клиента", f"79991234567 · {hash_phone('79991234567')}"),
        (
            "Номер А",
            f"79991234567 · {hash_phone('79991234567')}, "
            f"79211234567 · {hash_phone('79211234567')}",
        ),
        ("Номер Б", f"73912777454 · {hash_phone('73912777454')}"),
        ("Дата и время", "04.05.2026 10:49:00"),
        ("Регион", "Москва (UTC+3)"),
        ("Дата создания заявки", "04.05.2026 09:12:30"),
        ("UUID звонка", "12345678-1234-5678-1234-567812345678"),
        ("Окно поиска", "120 мин"),
        ("Продукт", "Запись"),
    ]


def test_case_summary_fields_marks_partial_phone_a():
    ctx = {
        "phone_a_values": ["7999"],
        "phone_a_partial": True,
        "tz": "Europe/Moscow",
    }

    fields = case_summary_fields(ctx)

    assert ("Номер А", f"7999 · {hash_phone('7999')} — распознан частично") in fields


def test_case_summary_fields_joins_multiple_event_times():
    ctx = {
        "event_datetimes": [
            datetime(2026, 5, 4, 10, 49),
            datetime(2026, 5, 4, 11, 1),
        ],
        "tz": "Europe/Moscow",
    }

    fields = case_summary_fields(ctx)

    assert ("Дата и время", "04.05.2026 10:49:00, 04.05.2026 11:01:00") in fields
    # Без региона показываем хотя бы таймзону со смещением
    assert ("Часовой пояс", "Europe/Moscow (UTC+3)") in fields


def test_case_summary_fields_skips_empty_values():
    assert case_summary_fields({}) == []
    assert case_summary_fields({"msisdn": None, "window": None, "region": None}) == []


def test_case_summary_fields_marks_general_problem_scope():
    ctx = {
        "msisdn": "79991234567",
        "problem_scope": "general",
        "tz": "Europe/Moscow",
    }

    fields = case_summary_fields(ctx)

    assert ("Общая проблема", "да") in fields
    assert ("Продукт", "Запись") not in fields


def test_case_summary_fields_falls_back_to_product_key():
    fields = case_summary_fields({"tz": "Europe/Moscow"}, "не-существует")

    assert ("Продукт", "не-существует") in fields
