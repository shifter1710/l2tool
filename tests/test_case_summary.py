from datetime import datetime

from core.case_summary import case_summary_fields
from core.utils import hash_phone


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
