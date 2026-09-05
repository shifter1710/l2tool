from datetime import date, datetime, timedelta

import pytest

from core import parser


def test_normalize_phone_formats():
    cases = {
        "79991234567": "79991234567",
        "+79991234567": "79991234567",
        "89991234567": "79991234567",
        "8 (999) 123-45-67": "79991234567",
        "+7 (999) 123-45-67": "79991234567",
        "999 123-45-67": "79991234567",
        "84232253015": "74232253015",
        "4232253015": "74232253015",
        "74951234567": "74951234567",
    }

    for raw, expected in cases.items():
        assert parser.normalize_phone(raw) == expected


def test_normalize_phone_invalid_formats(capsys):
    assert parser.normalize_phone("12345") is None
    assert parser.normalize_phone("14951234567") is None

    warnings = capsys.readouterr().err
    assert "[WARN] Не удалось нормализовать номер: 12345" in warnings
    assert "[WARN] Не удалось нормализовать номер: 14951234567" in warnings


def test_empty_phone_values_are_not_normalized():
    for raw in (
        "любой",
        "любой номер",
        "все",
        "все звонки",
        "все номера",
        "все номера не записались",
        "не знает",
        "не указал",
        "нет",
        "не указан",
        "неизвестно",
        "-",
        "",
    ):
        assert parser.normalize_phone(raw) is None


def test_parse_normalizes_all_phone_fields():
    ctx = parser.parse("""Номер клиента (msisdn): +7 (999) 123-45-67
Номер звонящего (А): 8 (423) 225-30-15
Номер принимающего звонок (Б): 999 111-22-33
""")

    assert ctx["msisdn"] == "79991234567"
    assert ctx["phone_a"] == "74232253015"
    assert ctx["phone_b"] == "79991112233"


def test_parse_keeps_empty_phone_a_raw_without_normalizing():
    ctx = parser.parse("""Номер клиента (msisdn): 79144880859
Номер звонящего (А): любой
Номер принимающего звонок (Б): 914 488 0859
""")

    assert ctx["phone_a_raw"] == "любой"
    assert ctx["phone_a"] is None
    assert ctx["phone_b"] == "79144880859"
    assert ctx["msisdn"] == "79144880859"


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


def test_parse_event_datetimes_without_year_uses_current_year():
    past = datetime.now() - timedelta(days=30)
    result = parser.parse_event_datetimes(f"{past:%d.%m} 10:08")

    assert result == [datetime(past.year, past.month, past.day, 10, 8)]


def test_date_without_year_in_future_rolls_back_to_previous_year():
    _match, event_date = parser._event_date_match("15.12 10:00", today=date(2026, 9, 2))

    assert event_date == date(2025, 12, 15)


def test_date_without_year_in_future_keeps_leap_day():
    _match, event_date = parser._event_date_match("29.02", today=date(2024, 1, 1))

    assert event_date == date(2024, 2, 29)


def test_date_with_explicit_year_is_never_rolled_back():
    _match, event_date = parser._event_date_match("15.12.2030", today=date(2026, 9, 2))

    assert event_date == date(2030, 12, 15)


def test_parse_problem_call_datetime_without_year_variants():
    current_year = datetime.now().year
    cases = [
        "01.07 10:08",
        "01.07, 10:08",
        "01.07 в 10:08",
        "01.07 10-08",
        "01.07 10.08",
    ]

    for raw in cases:
        ctx = parser.parse(f"Дата и время проблемного звонка: {raw}")

        assert str(ctx["event_date"]) == f"{current_year}-07-01"
        assert str(ctx["event_time"]) == f"{current_year}-07-01 10:08:00"
        assert [str(value) for value in ctx["event_datetimes"]] == [
            f"{current_year}-07-01 10:08:00"
        ]


def test_parse_multiple_times_after_problem_call_date():
    ctx = parser.parse("Дата и время проблемного звонка: 04.05.2026  10-49    11-01")

    assert [str(value) for value in ctx["event_datetimes"]] == [
        "2026-05-04 10:49:00",
        "2026-05-04 11:01:00",
    ]
    assert str(ctx["event_time"]) == "2026-05-04 10:49:00"


def test_parse_comma_date_and_time_separators():
    cases = {
        "02,07,2026 10:16": ["2026-07-02 10:16:00"],
        "28.06.2026 15,24": ["2026-06-28 15:24:00"],
        "02,07,2026 10,16": ["2026-07-02 10:16:00"],
    }

    for raw, expected in cases.items():
        ctx = parser.parse(f"Дата и время проблемного звонка: {raw}")

        assert [str(value) for value in ctx["event_datetimes"]] == expected


def test_parse_two_digit_year_and_hour_range():
    ctx = parser.parse(
        "Дата и время проблемного звонка: 19.05.26, примерно днем, с 12 до 16"
    )

    assert str(ctx["event_date"]) == "2026-05-19"
    assert tuple(str(value) for value in ctx["event_time_range"]) == (
        "2026-05-19 12:00:00",
        "2026-05-19 16:00:00",
    )
    assert ctx["event_datetimes"] == []


def test_parse_times_before_shared_date():
    ctx = parser.parse(
        "Дата и время проблемного звонка: 16.37 и 16.13 и 16.04 01.07.2026"
    )

    assert [str(value) for value in ctx["event_datetimes"]] == [
        "2026-07-01 16:37:00",
        "2026-07-01 16:13:00",
        "2026-07-01 16:04:00",
    ]


def test_parse_time_before_date():
    ctx = parser.parse("Дата и время проблемного звонка: 19:43 05.07.2026")

    assert str(ctx["event_time"]) == "2026-07-05 19:43:00"


def test_parse_prefixed_date_without_time():
    ctx = parser.parse("Дата и время проблемного звонка: С 14.06.2026")

    assert str(ctx["event_date"]) == "2026-06-14"
    assert ctx["event_time"] is None


def test_date_range_is_general_problem_for_previous_day():
    ctx = parser.parse(
        """Дата и время проблемного звонка: 23.06.-30.06.
Дата отправки: 20.07.2026 16:55:24
"""
    )

    assert str(ctx["event_date"]) == "2026-07-19"
    assert ctx["event_time"] is None
    assert ctx["event_datetimes"] == []
    assert ctx["problem_scope"] == "general"
    assert ctx["event_date_source"] == "fallback_yesterday"


def test_general_problem_phrases_use_day_before_submission():
    for raw in ("Любые звонки в июне", "все время", "Вчера."):
        ctx = parser.parse(
            f"""Дата и время проблемного звонка: {raw}
Дата отправки: 20.07.2026 16:55:24
"""
        )

        assert str(ctx["event_date"]) == "2026-07-19"
        assert ctx["problem_scope"] == "general"


def test_time_only_uses_submission_date_when_earlier():
    for raw in ("11:03:25", "13:25", "14:14"):
        ctx = parser.parse(
            f"""Дата и время проблемного звонка: {raw}
Дата отправки: 20.07.2026 16:55:24
"""
        )

        assert str(ctx["event_date"]) == "2026-07-20"
        assert str(ctx["event_time"]).startswith(f"2026-07-20 {raw}")
        assert ctx["event_date_source"] == "ticket_submitted_at"


def test_time_only_uses_moscow_creation_time_converted_to_region():
    ctx = parser.parse(
        """Дата и время проблемного звонка: 18:00
Дата создания ЕИ: 20.07.2026 16:55:24
Местонахождение абонента: Красноярский край
"""
    )

    assert str(ctx["event_date"]) == "2026-07-20"
    assert str(ctx["event_time"]) == "2026-07-20 18:00:00"
    assert ctx["event_date_source"] == "ticket_submitted_at"


def test_time_only_later_than_submission_stays_unresolved():
    ctx = parser.parse(
        """Дата и время проблемного звонка: 18:00
Дата отправки: 20.07.2026 16:55:24
"""
    )

    assert ctx["event_date"] is None
    assert ctx["event_time"] is None


def test_parse_russian_month_and_compact_date():
    russian = parser.parse("Дата и время проблемного звонка: 14 июля 2026 20:12")
    compact = parser.parse("Дата и время проблемного звонка: 17072026")

    assert str(russian["event_time"]) == "2026-07-14 20:12:00"
    assert str(compact["event_date"]) == "2026-07-17"
    assert compact["event_time"] is None


def test_parse_multiple_phone_values_and_short_number():
    ctx = parser.parse(
        """Номер звонящего (А): 89189846065, 89028914449
Номер принимающего звонок (Б): 79370019995 79240424268
"""
    )
    short = parser.parse("Номер звонящего (А): 3301870")

    assert ctx["phone_a_values"] == ["79189846065", "79028914449"]
    assert ctx["phone_b_values"] == ["79370019995", "79240424268"]
    assert short["phone_a"] == "3301870"
    assert short["phone_a_values"] == ["3301870"]


def test_parse_partial_phone_prefix():
    ctx = parser.parse(
        "Номер звонящего (А): +7916.. в разделе звонки не отображается информация"
    )

    assert ctx["phone_a"] == "916"
    assert ctx["phone_a_values"] == ["916"]
    assert ctx["phone_a_partial"] is True


def test_parse_phone_comment_datetime():
    ctx = parser.parse(
        "Номер принимающего звонок (Б): 9394928585 11,06,2026 10/25 3 мин разговор."
    )

    assert ctx["phone_b"] == "79394928585"
    assert str(ctx["event_time"]) == "2026-06-11 10:25:00"


@pytest.mark.parametrize(
    ("region", "tz"),
    [
        ("Таймырский АО", "Asia/Krasnoyarsk"),
        ("Таймырский (Долгано-Ненецкий) округ", "Asia/Krasnoyarsk"),
        ("Эвенкийский автономный округ", "Asia/Krasnoyarsk"),
        ("Республика Башкортостан", "Asia/Yekaterinburg"),
        ("Тюменская область", "Asia/Yekaterinburg"),
        ("Ямало-Ненецкий автономный округ", "Asia/Yekaterinburg"),
        ("Ненецкий АО", "Europe/Moscow"),
        ("Коми-Пермяцкий округ", "Asia/Yekaterinburg"),
        ("Республика Коми", "Europe/Moscow"),
        ("Томская область", "Asia/Tomsk"),
        ("Омская область", "Asia/Omsk"),
        ("Республика Саха (Якутия)", "Asia/Yakutsk"),
        ("Амурская область", "Asia/Yakutsk"),
        ("Комсомольск-на-Амуре", "Asia/Vladivostok"),
        ("Сахалинская область", "Asia/Sakhalin"),
        ("Вологодская область", "Europe/Moscow"),
        ("Забайкальский край", "Asia/Chita"),
    ],
)
def test_region_timezone_resolution(region, tz):
    from core.timezones import resolve_timezone

    assert resolve_timezone(region) == tz
