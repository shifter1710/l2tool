import json
import os

import pytest

from core import reference_codes


def write_reference(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_load_store_without_file_is_empty(tmp_path):
    assert reference_codes.load_store(tmp_path / "reference_codes.json") == {}


def test_load_store_reads_valid_file(tmp_path):
    path = tmp_path / "reference_codes.json"
    write_reference(path, {"Decision": {"10": "Абонент вне зоны покрытия"}})

    assert reference_codes.load_store(path) == {
        "Decision": {"10": "Абонент вне зоны покрытия"}
    }


def test_load_store_with_broken_file_is_empty_and_logs_once(tmp_path, caplog):
    path = tmp_path / "reference_codes.json"
    path.write_text("{broken json", encoding="utf-8")
    reference_codes._LOAD_ERROR_LOGGED.clear()

    with caplog.at_level("WARNING", logger="core.reference_codes"):
        assert reference_codes.load_store(path) == {}
        assert reference_codes.load_store(path) == {}

    warnings = [record for record in caplog.records if "справочник" in record.getMessage().lower()]
    assert len(warnings) == 1


@pytest.mark.parametrize(
    "data",
    [
        "not-a-dict",
        {"Decision": ["10"]},
        {"Decision": {"10": ""}},
        {"Decision": {"": "текст"}},
        {"Decision": {"A" * 17: "текст"}},
        {"Decision": {str(i): "текст" for i in range(1001)}},
        {"Decision": {"10": "x" * 501}},
    ],
)
def test_load_store_rejects_invalid_data(tmp_path, data):
    path = tmp_path / "reference_codes.json"
    write_reference(path, data)
    reference_codes._LOAD_ERROR_LOGGED.clear()

    assert reference_codes.load_store(path) == {}


def test_load_store_rejects_oversized_file(tmp_path):
    path = tmp_path / "reference_codes.json"
    path.write_text('"pad" + "' + "x" * (reference_codes.MAX_FILE_SIZE + 1) + '"', encoding="utf-8")

    assert reference_codes.load_store(path) == {}


def test_write_store_is_atomic_with_restricted_permissions(tmp_path):
    path = tmp_path / "reference_codes.json"
    groups = {"Decision": {"10": "Вне покрытия"}}

    reference_codes.write_store(groups, path=path)

    assert reference_codes.load_store(path) == groups
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(path.parent.glob(".reference_codes.json.*")) == []


def test_find_codes_detects_all_syntax_variants(tmp_path):
    path = tmp_path / "reference_codes.json"
    write_reference(path, {"Decision": {"10": "Вне покрытия"}, "Reason": {"7": "MGW"}})

    hints = reference_codes.find_codes(
        "Decision 10, потом reason: 7 и Decision=10 снова", path=path
    )

    assert hints == [
        {"group": "Decision", "code": "10", "text": "Вне покрытия"},
        {"group": "Reason", "code": "7", "text": "MGW"},
    ]


def test_find_codes_keeps_text_order_and_deduplicates(tmp_path):
    path = tmp_path / "reference_codes.json"
    write_reference(path, {"Decision": {"10": "Первый", "20": "Второй"}})

    hints = reference_codes.find_codes("Decision 20 ... Decision 10 ... Decision 20", path=path)

    assert [hint["code"] for hint in hints] == ["20", "10"]


def test_find_codes_ignores_unknown_and_unrelated_numbers(tmp_path):
    path = tmp_path / "reference_codes.json"
    write_reference(path, {"Decision": {"10": "Вне покрытия"}})

    assert reference_codes.find_codes("Decision 99 и Reason 10, номер 79991234567", path=path) == []
    assert reference_codes.find_codes("Decision1234", path=path) == []


def test_import_store_replaces_content_and_counts_entries(tmp_path):
    path = tmp_path / "reference_codes.json"
    write_reference(path, {"Old": {"1": "старое"}})
    content = json.dumps({"Decision": {"10": "Новое", "20": "Ещё"}}, ensure_ascii=False)

    count = reference_codes.import_store(content, path=path)

    assert count == 2
    assert reference_codes.load_store(path) == {"Decision": {"10": "Новое", "20": "Ещё"}}


def test_import_store_keeps_previous_content_on_invalid_file(tmp_path):
    path = tmp_path / "reference_codes.json"
    write_reference(path, {"Old": {"1": "старое"}})

    with pytest.raises(ValueError):
        reference_codes.import_store("{broken", path=path)
    with pytest.raises(ValueError):
        reference_codes.import_store('{"Decision": {"10": ""}}', path=path)

    assert reference_codes.load_store(path) == {"Old": {"1": "старое"}}


def test_export_store_returns_current_file(tmp_path):
    path = tmp_path / "reference_codes.json"
    content = json.dumps({"Decision": {"10": "Вне покрытия"}}, ensure_ascii=False, indent=2) + "\n"
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)

    assert reference_codes.export_store(path=path) == content


def test_export_store_without_file_returns_empty_object(tmp_path):
    assert reference_codes.export_store(tmp_path / "reference_codes.json") == "{}\n"
