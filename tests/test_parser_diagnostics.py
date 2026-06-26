import json

import gtool
from core import parser
from core.parser_diagnostics import collect_parse_issues, write_parse_issues


def test_bad_phone_creates_issue_and_warning(monkeypatch, tmp_path):
    text = "Номер клиента (msisdn): 74951234567"

    ctx = parser.parse(text)
    issues = collect_parse_issues(text, ctx)

    assert issues == [
        {
            "field": "msisdn",
            "reason": "phone_normalization_failed",
            "line": 1,
            "message": "Номер клиента не распознан: 74951234567",
        }
    ]

    issues_path = tmp_path / "parser_issues.jsonl"
    write_parse_issues(issues, path=issues_path)

    saved = issues_path.read_text(encoding="utf-8").splitlines()
    assert len(saved) == 1
    assert json.loads(saved[0]) == issues[0]

    monkeypatch.setattr(gtool, "write_parse_issues", lambda issues: None)
    result = gtool.run_ticket(text, open_arg="zapis")

    assert any(line.startswith("[WARN] Проблема парсинга:") for line in result.lines)


def test_ignore_values_do_not_create_issues():
    text = """Номер клиента (msisdn): любой
Номер звонящего (А): нет
Номер принимающего звонок (Б): -
Дата и время проблемного звонка: неизвестно
"""

    assert collect_parse_issues(text, parser.parse(text)) == []


def test_bad_datetime_creates_issue():
    text = "Дата и время проблемного звонка: 32.03.2026 12:00"

    issues = collect_parse_issues(text, parser.parse(text))

    assert issues == [
        {
            "field": "event_datetime",
            "reason": "datetime_parse_failed",
            "line": 1,
            "message": "Дата и время проблемного звонка не распознано: 32.03.2026 12:00",
        }
    ]
