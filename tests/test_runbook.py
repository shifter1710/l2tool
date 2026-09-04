import json

import pytest

from core import runbook


def write_runbook(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def sample_case(case_id="no-transcript"):
    return {
        "id": case_id,
        "symptom": "Запись есть, транскрипта нет",
        "steps": [
            {"source": "abc12345", "note": "Проверить приход звонка в конвейер"},
            {"source": None, "note": "Уточнить у абонента детали"},
        ],
    }


def test_load_store_without_file_is_empty(tmp_path):
    assert runbook.load_store(tmp_path / "runbook.json") == []


def test_load_store_reads_valid_file(tmp_path):
    path = tmp_path / "runbook.json"
    write_runbook(path, [sample_case()])

    cases = runbook.load_store(path)
    assert cases == [sample_case()]
    assert cases[0]["steps"][1]["source"] is None


def test_load_store_with_broken_file_is_empty_and_logs_once(tmp_path, caplog):
    path = tmp_path / "runbook.json"
    path.write_text("{broken json", encoding="utf-8")
    runbook._LOAD_ERROR_LOGGED.clear()

    with caplog.at_level("WARNING", logger="core.runbook"):
        assert runbook.load_store(path) == []
        assert runbook.load_store(path) == []

    warnings = [record for record in caplog.records if "ранбук" in record.getMessage().lower()]
    assert len(warnings) == 1


def test_load_store_rejects_oversized_file(tmp_path):
    path = tmp_path / "runbook.json"
    path.write_text("x" * (runbook.MAX_FILE_SIZE + 1), encoding="utf-8")
    runbook._LOAD_ERROR_LOGGED.clear()

    assert runbook.load_store(path) == []


@pytest.mark.parametrize(
    "case",
    [
        {"id": "", "symptom": "Симптом", "steps": [{"source": None, "note": "Шаг"}]},
        {"id": "Плохой ID", "symptom": "Симптом", "steps": [{"source": None, "note": "Шаг"}]},
        {"id": "ok", "symptom": "", "steps": [{"source": None, "note": "Шаг"}]},
        {"id": "ok", "symptom": "с" * 201, "steps": [{"source": None, "note": "Шаг"}]},
        {"id": "ok", "symptom": "Симптом", "steps": []},
        {"id": "ok", "symptom": "Симптом", "steps": [{"source": None, "note": ""}]},
        {"id": "ok", "symptom": "Симптом", "steps": [{"source": None, "note": "н" * 501}]},
        {"symptom": "Симптом", "steps": [{"source": None, "note": "Шаг"}]},
    ],
)
def test_validate_case_rejects_bad_fields(case):
    with pytest.raises(ValueError):
        runbook.validate_case(case)


def test_validate_store_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="повторяется"):
        runbook.validate_store([sample_case(), sample_case()])


def test_validate_store_rejects_too_many_cases():
    cases = [sample_case(f"case-{index}") for index in range(runbook.MAX_CASES + 1)]
    with pytest.raises(ValueError, match="кейсов"):
        runbook.validate_store(cases)


def test_validate_case_rejects_too_many_steps():
    case = sample_case()
    case["steps"] = [{"source": None, "note": "Шаг"}] * (runbook.MAX_STEPS + 1)
    with pytest.raises(ValueError, match="шагов"):
        runbook.validate_case(case)


def test_write_store_is_atomic_with_private_permissions(tmp_path):
    path = tmp_path / "runbook.json"
    runbook.write_store([sample_case()], path)

    assert json.loads(path.read_text(encoding="utf-8")) == [sample_case()]
    assert oct(path.stat().st_mode)[-3:] == "600"
    assert not list(tmp_path.glob("*.tmp"))


def test_save_case_creates_updates_and_backup(tmp_path):
    path = tmp_path / "runbook.json"
    created = runbook.save_case(sample_case(), path=path)
    assert created["id"] == "no-transcript"
    assert runbook.load_store(path) == [created]

    updated = dict(sample_case(), symptom="Другой симптом")
    runbook.save_case(updated, case_id="no-transcript", path=path)
    cases = runbook.load_store(path)
    assert len(cases) == 1
    assert cases[0]["symptom"] == "Другой симптом"

    backups = list((tmp_path / "backups").glob("runbook.*.json"))
    assert len(backups) == 1

    with pytest.raises(ValueError, match="не найден"):
        runbook.delete_case("missing", path=path)

    runbook.delete_case("no-transcript", path=path)
    assert runbook.load_store(path) == []
    backups = list((tmp_path / "backups").glob("runbook.*.json"))
    assert len(backups) == 2


def test_save_case_generates_id_when_missing(tmp_path):
    path = tmp_path / "runbook.json"
    values = {"symptom": "Симптом", "steps": [{"source": None, "note": "Шаг"}]}
    case = runbook.save_case(values, path=path)
    assert case["id"].startswith("case-")


def test_import_and_export_roundtrip(tmp_path):
    path = tmp_path / "runbook.json"
    content = json.dumps([sample_case()], ensure_ascii=False)
    count = runbook.import_store(content, path=path)

    assert count == 1
    assert json.loads(runbook.export_store(path)) == [sample_case()]


def test_import_store_rejects_invalid_content_without_replacing(tmp_path):
    path = tmp_path / "runbook.json"
    runbook.write_store([sample_case()], path)
    with pytest.raises(ValueError):
        runbook.import_store(json.dumps([{"id": "x", "symptom": "", "steps": []}]), path=path)
    assert runbook.load_store(path) == [sample_case()]


def test_import_store_rejects_oversized_file(tmp_path):
    content = json.dumps([sample_case()]) + " " * (runbook.MAX_FILE_SIZE + 1)
    with pytest.raises(ValueError, match="256 КБ"):
        runbook.import_store(content, path=tmp_path / "runbook.json")


def test_export_store_without_file_is_empty_list(tmp_path):
    assert json.loads(runbook.export_store(tmp_path / "runbook.json")) == []


def test_backup_rotates_old_copies(tmp_path):
    path = tmp_path / "runbook.json"
    runbook.write_store([sample_case()], path)
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    for index in range(runbook.BACKUP_KEEP + 2):
        (backups_dir / f"runbook.20260904-0000{index:02d}.json").write_text("{}", encoding="utf-8")

    runbook.create_backup(path)

    remaining = sorted(item.name for item in backups_dir.glob("runbook.*.json"))
    assert len(remaining) == runbook.BACKUP_KEEP
    assert "runbook.20260904-000000.json" not in remaining
