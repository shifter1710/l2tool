from core import parser


def test_normalize_msisdn_formats():
    cases = {
        "79991234567": "79991234567",
        "+79991234567": "79991234567",
        "89991234567": "79991234567",
        "8 (999) 123-45-67": "79991234567",
        "+7 (999) 123-45-67": "79991234567",
        "999 123-45-67": "79991234567",
    }

    for raw, expected in cases.items():
        assert parser.normalize_msisdn(raw) == expected


def test_normalize_msisdn_invalid_formats():
    assert parser.normalize_msisdn("12345") is None
    assert parser.normalize_msisdn("74951234567") is None


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
