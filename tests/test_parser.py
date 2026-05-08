from core import parser


def test_normalize_phone_formats():
    cases = {
        "79991234567": "79991234567",
        "+79991234567": "79991234567",
        "89991234567": "79991234567",
        "8 (999) 123-45-67": "79991234567",
        "+7 (999) 123-45-67": "79991234567",
        "999 123-45-67": "79991234567",
    }

    for raw, expected in cases.items():
        assert parser.normalize_phone(raw) == expected


def test_normalize_phone_invalid_formats():
    assert parser.normalize_phone("12345") is None
    assert parser.normalize_phone("74951234567") is None


def test_parse_normalizes_all_phone_fields():
    ctx = parser.parse("""Номер клиента (msisdn): +7 (999) 123-45-67
Номер звонящего (А): 8 (999) 765-43-21
Номер принимающего звонок (Б): 999 111-22-33
""")

    assert ctx["msisdn"] == "79991234567"
    assert ctx["phone_a"] == "79997654321"
    assert ctx["phone_b"] == "79991112233"


def test_parse_callee_landline_phone_b():
    ctx = parser.parse("Номер принимающего звонок (Б): 83912777454")

    assert ctx["phone_b"] == "73912777454"
    assert ctx["number_b"] == "73912777454"
    assert ctx["callee"] == "73912777454"


def test_parse_phone_b_field_variants():
    cases = [
        "Номер принимающего звонок (Б): 83912777454",
        "Номер принимающего звонок Б: 83912777454",
        "Номер Б: 83912777454",
        "Б: 83912777454",
        "callee: 83912777454",
    ]

    for raw in cases:
        assert parser.parse(raw)["phone_b"] == "73912777454"


def test_date_only_is_not_time():
    assert parser.parse_time_value("31.03.2026") is None


def test_hh_mm_is_time():
    assert str(parser.parse_time_value("12:30")) == "12:30:00"


def test_hh_mm_ss_is_time():
    assert str(parser.parse_time_value("12:30:45")) == "12:30:45"


def test_parse_msisdn_without_datetime():
    ctx = parser.parse("Номер клиента (msisdn): 79990000000")

    assert ctx["msisdn"] == "79990000000"
    assert ctx["event_time"] is None


def test_parse_date_only_without_datetime():
    ctx = parser.parse("""Номер клиента (msisdn): 79990000000
Дата и время проблемного звонка: 31.03.2026
""")

    assert str(ctx["event_date"]) == "2026-03-31"
    assert ctx["event_clock"] is None
    assert ctx["event_time"] is None


def test_parse_separate_date_and_time():
    ctx = parser.parse("""Номер клиента (msisdn): 79990000000
Дата: 31.03.2026
Время: 12:30
""")

    assert str(ctx["event_date"]) == "2026-03-31"
    assert str(ctx["event_clock"]) == "12:30:00"
    assert str(ctx["event_time"]) == "2026-03-31 12:30:00"


def test_parse_problem_call_datetime_with_comma():
    ctx = parser.parse("""Номер клиента (msisdn): 79990000000
Дата и время проблемного звонка: 04.05.2026, 12:28
""")

    assert str(ctx["event_date"]) == "2026-05-04"
    assert str(ctx["event_time"]) == "2026-05-04 12:28:00"


def test_parse_datetime_variants():
    cases = [
        "04.05.2026 12:28",
        "04.05.2026, 12:28",
        "04.05.2026 в 12:28",
        "04.05.2026 12:28:45",
    ]

    for raw in cases:
        assert parser.parse_datetime_value(raw) is not None
