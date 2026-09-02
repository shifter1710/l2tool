import json
import stat

import gtool
from core import parser
from core.parser_diagnostics import collect_parse_issues, write_parse_issues


def test_bad_phone_creates_issue_and_warning(monkeypatch, tmp_path):
    text = """Номер клиента (msisdn): 14951234567
Дата и время проблемного звонка: 04.05.2026 10:30
"""

    ctx = parser.parse(text)
    issues = collect_parse_issues(text, ctx)

    assert issues == [
        {
            "field": "msisdn",
            "reason": "phone_normalization_failed",
            "line_number": 1,
            "line_text": "Номер клиента (msisdn): 14951234567",
            "message": "Номер клиента не распознан: 14951234567",
        }
    ]

    issues_path = tmp_path / "parser_issues.jsonl"
    write_parse_issues(issues, path=issues_path)

    saved = issues_path.read_text(encoding="utf-8").splitlines()
    assert len(saved) == 1
    assert json.loads(saved[0]) == issues[0]
    assert stat.S_IMODE(issues_path.stat().st_mode) == 0o600

    monkeypatch.setattr(gtool, "write_parse_issues", lambda issues: None)
    result = gtool.run_ticket(text, open_arg="zapis")

    assert result.links_by_module == {}
    assert "[ERROR] Номер клиента не распознан: 14951234567" in result.lines
    assert "  Строка 1: Номер клиента (msisdn): 14951234567" in result.lines


def test_issue_location_skips_blank_lines_before_indented_field():
    text = "\n  Номер клиента (msisdn): 14951234567"

    issues = collect_parse_issues(text, parser.parse(text))

    assert issues[0]["line_number"] == 2
    assert issues[0]["line_text"] == "  Номер клиента (msisdn): 14951234567"


def test_diagnostic_uses_same_field_precedence_as_parser():
    text = """Номер клиента: 14951234567
Номер клиента (msisdn): 12345
"""

    ctx = parser.parse(text)
    issues = collect_parse_issues(text, ctx)

    assert ctx["msisdn_raw"] == "12345"
    assert issues[0]["line_number"] == 2
    assert issues[0]["line_text"] == "Номер клиента (msisdn): 12345"
    assert issues[0]["message"] == "Номер клиента не распознан: 12345"


def test_ignore_values_do_not_create_issues():
    text = """Номер клиента (msisdn): любой
Номер звонящего (А): нет
Номер принимающего звонок (Б): -
Дата и время проблемного звонка: неизвестно
"""

    issues = collect_parse_issues(text, parser.parse(text))

    assert issues == [
        {
            "field": "event_datetime",
            "reason": "event_time_missing",
            "line_number": 4,
            "line_text": "Дата и время проблемного звонка: неизвестно",
            "message": "Дата и время звонка не найдены",
        }
    ]


def test_anti_caller_id_value_does_not_create_phone_issue():
    text = """Номер клиента (msisdn): 79991234567
Номер звонящего (А): Номер с услугой Антиопределитель номера
Дата и время проблемного звонка: 28.08.2026 12:00
"""

    ctx = parser.parse(text)

    assert ctx["phone_a"] is None
    assert collect_parse_issues(text, ctx) == []


def test_missing_event_time_creates_issue_without_source_line():
    issues = collect_parse_issues(
        "Номер клиента (msisdn): 79991234567",
        parser.parse("Номер клиента (msisdn): 79991234567"),
    )

    assert issues == [
        {
            "field": "event_datetime",
            "reason": "event_time_missing",
            "line_number": 0,
            "line_text": "",
            "message": "Дата и время звонка не найдены",
        }
    ]


def test_bad_datetime_creates_issue():
    text = "Дата и время проблемного звонка: 32.03.2026 12:00"

    issues = collect_parse_issues(text, parser.parse(text))

    assert issues == [
        {
            "field": "event_datetime",
            "reason": "datetime_parse_failed",
            "line_number": 1,
            "line_text": "Дата и время проблемного звонка: 32.03.2026 12:00",
            "message": "Дата и время проблемного звонка не распознано: 32.03.2026 12:00",
        }
    ]


def test_datetime_without_year_does_not_create_issue():
    text = "Дата и время проблемного звонка: 01.07 10:08"

    assert collect_parse_issues(text, parser.parse(text)) == []


def test_date_without_time_does_not_create_datetime_issue():
    text = "Дата и время проблемного звонка: 31.03.2026"

    assert collect_parse_issues(text, parser.parse(text)) == []


def test_common_unspecified_phone_values_only_require_event_time():
    text = """Номер звонящего (А): все номера не записываются
Номер принимающего звонок (Б): не знает
"""

    assert collect_parse_issues(text, parser.parse(text)) == [
        {
            "field": "event_datetime",
            "reason": "event_time_missing",
            "line_number": 0,
            "line_text": "",
            "message": "Дата и время звонка не найдены",
        }
    ]


def test_time_only_with_submission_date_does_not_create_issue():
    text = """Дата и время проблемного звонка: 13:25
Дата отправки: 20.07.2026 16:55:24
"""

    assert collect_parse_issues(text, parser.parse(text)) == []


def test_time_only_with_ei_creation_date_does_not_create_issue():
    text = """Дата и время проблемного звонка: 18:00
Дата создания ЕИ: 20.07.2026 16:55:24
Местонахождение абонента: Красноярский край
"""

    assert collect_parse_issues(text, parser.parse(text)) == []


def test_general_problem_date_range_does_not_create_issue():
    text = """Дата и время проблемного звонка: 23.06.-30.06.
Дата отправки: 20.07.2026 16:55:24
"""

    assert collect_parse_issues(text, parser.parse(text)) == []
