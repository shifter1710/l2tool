import json
import stat
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import pytest

from core.dynamic_sources import (
    build_product_links,
    build_source_links,
    build_source_links_labeled,
    create_product,
    delete_product,
    delete_source,
    duplicate_source,
    import_services_from_config,
    import_sources,
    is_managed,
    list_products,
    list_sources,
    load_store,
    move_source,
    preview_source,
    product_groups,
    save_source,
    set_product_sources_enabled,
    set_source_enabled,
    update_product,
    validate_source,
)
from core.products import available_products
from core.source_backups import list_backups, restore_backup
from core.utils import hash_phone

PHONE = "79991234567"
OTHER_PHONE = "79997654321"
CALL_UUID = "12345678-1234-5678-1234-567812345678"
OTHER_UUID = "87654321-4321-8765-4321-876543218765"


def context(phone=OTHER_PHONE, phone_b=None, client=None):
    return {
        "msisdn": client or phone,
        "phone_a": phone,
        "phone_b": phone_b,
        "event_time": datetime(2026, 9, 3, 14, 30),
        "event_datetimes": [datetime(2026, 9, 3, 14, 30)],
        "tz": "Europe/Moscow",
        "window": 60,
    }


def opensearch_url(value=PHONE):
    return (
        "https://dashboards.example.local/app/data-explorer/discover"
        "#?_a=(metadata:(indexPattern:custom-view),"
        f"query:(language:kuery,query:'msisdn:{value}'))"
        "&_g=(time:(from:'2026-09-03T11:00:00.000',to:'2026-09-03T12:00:00.000'))"
    )


def grafana_url(value=CALL_UUID):
    pane = {
        "datasource": "loki-custom",
        "queries": [{"refId": "A", "expr": f'{{job="calls"}} |= `{value}`'}],
        "range": {"from": "now-1h", "to": "now"},
    }
    return "https://grafana.example.local/explore?" + urlencode(
        {"panes": json.dumps({"A": pane}, separators=(",", ":")), "orgId": "1"}
    )


def grafana_dashboard_phone_pair():
    return (
        "https://grafana.example.local/d/calls/find-call-in-logs?orgId=1"
        "&var-phone=9835623921&var-second_phone=9994579778"
        "&from=2026-09-03T11:00:00.000Z&to=2026-09-03T12:00:00.000Z"
    )


def values(**overrides):
    result = {
        "name": "Пользовательский BFF",
        "product": "recording",
        "level": "number",
        "example_url": opensearch_url(),
        "sample_value": "",
        "minutes_before": "2",
        "minutes_after": "90",
    }
    result.update(overrides)
    return result


def test_opensearch_example_is_parsed_and_rebuilt_from_diagnostic_data():
    source = validate_source(values())
    links = build_source_links(source, context())

    assert source["index_pattern"] == "custom-view"
    assert source["strategy"] == "raw"
    assert len(links) == 1
    assert OTHER_PHONE in unquote(links[0])
    assert PHONE not in unquote(links[0])
    assert "2026-09-03T14:28:00.000" in unquote(links[0])


def test_hash_phone_strategy_uses_explicit_sample_value():
    source = validate_source(
        values(example_url=opensearch_url(hash_phone(PHONE)), sample_value=PHONE)
    )

    assert source["strategy"] == "hash16"
    assert hash_phone(OTHER_PHONE) in unquote(build_source_links(source, context())[0])


def test_two_phone_slots_create_one_link_with_phone_a_and_phone_b():
    source = validate_source(
        values(example_url=grafana_dashboard_phone_pair(), sample_value="")
    )
    links = build_source_links(source, context(phone="79209264847", phone_b="79157771575"))
    query = parse_qs(urlsplit(links[0]).query)

    assert len(source["replacements"]) == 2
    assert len(links) == 1
    assert query["var-phone"] == ["9209264847"]
    assert query["var-second_phone"] == ["9157771575"]
    assert "9835623921" not in links[0]
    assert "9994579778" not in links[0]


@pytest.mark.parametrize(
    ("phone_a", "phone_b", "client", "expected_a", "expected_b"),
    [
        (None, None, "79991234567", "9991234567", ""),
        ("79209264847", None, "79157771575", "9209264847", "9157771575"),
        (None, "79209264847", "79157771575", "9157771575", "9209264847"),
    ],
)
def test_two_phone_slots_fill_missing_side_with_client_number(
    phone_a, phone_b, client, expected_a, expected_b
):
    source = validate_source(
        values(example_url=grafana_dashboard_phone_pair(), sample_value="")
    )
    ctx = context(phone=phone_a, phone_b=phone_b, client=client)
    ctx["phone_a"] = phone_a
    link = build_source_links(source, ctx)[0]
    query = parse_qs(urlsplit(link).query, keep_blank_values=True)

    assert query["var-phone"] == [expected_a]
    assert query["var-second_phone"] == [expected_b]


def test_grafana_uuid_example_updates_query_and_time_range():
    source = validate_source(
        values(
            name="MGW",
            level="uuid",
            example_url=grafana_url(),
            sample_value="",
        )
    )
    link = build_source_links(source, context(), call_uuid=OTHER_UUID)[0]
    panes = json.loads(parse_qs(urlsplit(link).query)["panes"][0])

    assert OTHER_UUID in panes["A"]["queries"][0]["expr"]
    assert CALL_UUID not in panes["A"]["queries"][0]["expr"]
    assert panes["A"]["range"]["from"].endswith("Z")


def test_blocks_can_be_added_renamed_moved_and_deleted(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    created = save_source(values(), path=store)

    assert is_managed("recording", path=store)
    assert stat.S_IMODE(store.stat().st_mode) == 0o600
    renamed = save_source(
        values(name="Новое имя", product="calls", level="uuid", example_url=grafana_url()),
        source_id=created["id"],
        path=store,
    )
    assert renamed["name"] == "Новое имя"
    assert list_sources(product="calls", level="uuid", path=store)[0]["id"] == created["id"]
    assert product_groups(path=store)[0]["managed"] is True

    delete_source(created["id"], path=store)
    assert list_sources(path=store) == []
    assert is_managed("recording", path=store)


def test_import_adds_valid_blocks_skips_duplicates_and_is_atomic(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    payload = json.dumps({"version": 1, "sources": [values()]})

    first = import_sources(payload, path=store)
    second = import_sources(payload, path=store)

    assert first == {"added": 1, "skipped": 0}
    assert second == {"added": 0, "skipped": 1}
    assert len(list_sources(path=store)) == 1

    invalid_payload = json.dumps(
        {"sources": [values(name="Ещё один"), values(name="Сломан", example_url="bad")]}
    )
    with pytest.raises(ValueError, match="Блок 2"):
        import_sources(invalid_payload, path=store)
    assert len(list_sources(path=store)) == 1


def test_rejects_credentials_tokens_and_missing_sample():
    with pytest.raises(ValueError, match="логин и пароль"):
        validate_source(values(example_url="https://user:pass@example.local/explore?panes={}"))
    with pytest.raises(ValueError, match="токен"):
        validate_source(values(example_url=opensearch_url() + "&token=secret"))
    with pytest.raises(ValueError, match="значение-пример"):
        validate_source(values(example_url=opensearch_url("no-number")))


def test_opensearch_example_without_time_state_reports_error():
    url = (
        "https://dashboards.example.local/app/data-explorer/discover"
        "#?_a=(metadata:(indexPattern:custom-view),"
        "query:(language:kuery,query:'msisdn:79991234567'))"
    )
    source = validate_source(values(example_url=url))

    with pytest.raises(ValueError, match="временной диапазон"):
        build_source_links(source, context())


def fully_decoded(url):
    previous = url
    for _ in range(3):
        current = unquote(previous)
        if current == previous:
            break
        previous = current
    return previous


def test_v1_store_migrates_to_v2_in_memory_and_persists_on_first_change(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    store.write_text(
        json.dumps(
            {"version": 1, "managed_products": ["recording"], "sources": [values()]}
        ),
        encoding="utf-8",
    )

    data = load_store(store)

    assert data["version"] == 2
    assert [entry["key"] for entry in data["products"]] == [
        "recording",
        "secretary",
        "calls",
        "noise",
        "assistant",
    ]
    assert data["products"][0]["managed"] is True
    assert data["products"][1]["managed"] is False
    assert json.loads(store.read_text(encoding="utf-8"))["version"] == 1

    save_source(values(name="Ещё блок"), path=store)

    assert json.loads(store.read_text(encoding="utf-8"))["version"] == 2
    assert "managed_products" not in json.loads(store.read_text(encoding="utf-8"))


def test_custom_product_lifecycle(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    create_product("zapis-msk", "Запись МСК", "violet", path=store)

    assert is_managed("zapis-msk", path=store)
    assert available_products(path=store)[-1] == "zapis-msk"
    source = save_source(values(product="zapis-msk"), path=store)
    assert list_products(path=store)[-1]["source_count"] == 1

    update_product("zapis-msk", "Запись СПБ", "teal", new_key="zapis-spb", path=store)

    assert list_sources(path=store)[0]["product"] == "zapis-spb"
    assert "zapis-msk" not in available_products(path=store)

    with pytest.raises(ValueError, match="Сначала удалите"):
        delete_product("zapis-spb", path=store)

    delete_source(source["id"], path=store)
    delete_product("zapis-spb", path=store)

    assert "zapis-spb" not in available_products(path=store)


def test_builtin_products_are_protected_and_restorable(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    with pytest.raises(ValueError, match="Ключ встроенного продукта"):
        update_product("recording", "Новое имя", None, new_key="rec", path=store)
    with pytest.raises(ValueError, match="латиница"):
        create_product("Плохой Ключ", "Продукт", path=store)
    with pytest.raises(ValueError, match="уже существует"):
        create_product("recording", "Дубль", path=store)

    delete_product("assistant", path=store)
    assert "assistant" not in available_products(path=store)

    entry = create_product("assistant", "Ассистент в звонке", path=store)

    assert entry["builtin"] is True
    assert entry["managed"] is False
    assert is_managed("assistant", path=store) is False


def test_product_groups_include_custom_products(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    create_product("zapis-msk", "Запись МСК", "violet", path=store)
    save_source(values(product="zapis-msk"), path=store)

    groups = product_groups(path=store)

    assert groups[-1]["key"] == "zapis-msk"
    assert groups[-1]["title"] == "Запись МСК"
    assert groups[-1]["managed"] is True
    assert groups[-1]["levels"][0]["sources"][0]["name"] == "Пользовательский BFF"


def test_disabled_source_is_hidden_from_links_but_kept_in_settings(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    created = save_source(values(), path=store)

    set_source_enabled(created["id"], False, path=store)

    assert list_sources(path=store)[0]["enabled"] is False
    assert list_sources(path=store, enabled_only=True) == []

    links, titles, errors, _labels = build_product_links(
        "recording", "number", context(), path=store
    )
    assert links == {} and titles == {} and errors == []

    groups = product_groups(path=store)

    assert groups[0]["levels"][0]["sources"][0]["enabled"] is False

    set_source_enabled(created["id"], True, path=store)

    assert build_product_links("recording", "number", context(), path=store)[0]


def test_duplicate_source_copies_fields_with_new_id(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    created = save_source(values(), path=store)

    copy = duplicate_source(created["id"], path=store)

    assert copy["id"] != created["id"]
    assert copy["name"] == "Пользовательский BFF (копия)"
    assert copy["example_url"] == created["example_url"]
    assert [item["name"] for item in list_sources(path=store)] == [
        "Пользовательский BFF",
        "Пользовательский BFF (копия)",
    ]


def test_move_source_reorders_within_product_and_level(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    save_source(values(name="Первый"), path=store)
    second = save_source(
        values(name="Второй", example_url=opensearch_url("79997654321")), path=store
    )
    other_level = save_source(
        values(name="UUID уровень", level="uuid", example_url=grafana_url()), path=store
    )

    assert move_source(second["id"], "up", path=store) is True
    assert [item["name"] for item in list_sources(path=store)] == [
        "Второй",
        "Первый",
        "UUID уровень",
    ]
    assert move_source(second["id"], "up", path=store) is False

    links_order = [
        source["name"]
        for source in list_sources(product="recording", level="number", path=store)
    ]
    assert links_order == ["Второй", "Первый"]
    assert other_level["level"] == "uuid"


def test_bulk_toggle_changes_all_product_blocks(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    first = save_source(values(), path=store)
    second = save_source(
        values(name="Второй", example_url=opensearch_url("79997654321")), path=store
    )

    assert set_product_sources_enabled("recording", False, path=store) == 2
    assert list_sources(path=store, enabled_only=True) == []

    assert set_product_sources_enabled("recording", True, path=store) == 2
    assert len(list_sources(path=store, enabled_only=True)) == 2
    assert first["id"] != second["id"]


def test_preview_source_builds_links_without_writing_store(tmp_path):
    store = tmp_path / "diagnostic_sources.json"

    result = preview_source(values(), "79991230001", path=store)

    assert result["error"] is None
    assert len(result["links"]) == 1
    assert "msisdn:79991230001" in fully_decoded(result["links"][0])
    assert not store.exists()


def test_preview_source_reports_errors_without_saving(tmp_path):
    store = tmp_path / "diagnostic_sources.json"

    missing_sample = preview_source(
        values(example_url=opensearch_url("no-number-here")), "", path=store
    )
    bad_test_value = preview_source(values(), "не номер", path=store)

    assert "значение-пример" in missing_sample["error"]
    assert bad_test_value["error"]
    assert not store.exists()


def test_backups_rotate_and_restore(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    created = save_source(values(), path=store)

    for index in range(22):
        set_source_enabled(created["id"], index % 2 == 0, path=store)

    backups = list_backups(store)

    assert len(backups) == 20
    assert backups[0]["created"] >= backups[-1]["created"]
    assert all(backup["blocks"] == 1 for backup in backups)

    delete_source(created["id"], path=store)
    assert list_sources(path=store) == []

    restore_backup(list_backups(store)[0]["name"], store)

    assert [item["name"] for item in list_sources(path=store)] == ["Пользовательский BFF"]

    with pytest.raises(ValueError, match="Некорректное имя"):
        restore_backup("../diagnostic_sources.json", store)


def _config_toml(path, zapis_url, sip_url, bff_url):
    path.write_text(
        "\n".join(
            [
                f'[services.zapis]\nurl = "{zapis_url}"',
                "",
                f'[services.sip_stack]\nurl = "{sip_url}"',
                "",
                f'[services.bff]\nurl = "{bff_url}"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_import_services_from_config_reproduces_recording_profile(
    tmp_path, monkeypatch
):
    from core import config as config_module
    from modules import bff_logs_opensearch, find_call_in_logs, sip_stack_opensearch

    store = tmp_path / "diagnostic_sources.json"
    config_path = tmp_path / "config.toml"
    _config_toml(
        config_path,
        "https://grafana.example.local/d/example/find-call-in-logs?orgId=000",
        "https://dashboards.example.local/app/data-explorer/discover"
        "#?_a=(metadata:(indexPattern:sip-stack-example,view:discover))",
        "https://dashboards.example.local/app/data-explorer/discover"
        "#?_a=(metadata:(indexPattern:bff-example,view:discover))",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)

    seed_ctx = context(phone=PHONE, phone_b=OTHER_PHONE)
    zapis_url = find_call_in_logs.build(seed_ctx)[0]
    sip_url = sip_stack_opensearch.build(seed_ctx)[0]
    bff_url = bff_logs_opensearch.build(seed_ctx)[0]
    _config_toml(config_path, zapis_url, sip_url, bff_url)

    report = import_services_from_config(
        "recording", path=store, config_path=config_path, sample_value=PHONE
    )

    assert report == {"added": 3, "skipped": 0, "errors": []}
    assert is_managed("recording", path=store)

    ticket_ctx = context(phone="79209264847", phone_b="79157771575", client="79209264847")
    static_links = {
        "zapis": find_call_in_logs.build(ticket_ctx)[0],
        "sip_stack": sip_stack_opensearch.build(ticket_ctx)[0],
        "bff": bff_logs_opensearch.build(ticket_ctx)[0],
    }
    links, _titles, errors, _labels = build_product_links(
        "recording", "number", ticket_ctx, path=store
    )
    dynamic_links = {fully_decoded(link) for block_links in links.values() for link in block_links}

    assert errors == []
    for static_link in static_links.values():
        assert fully_decoded(static_link) in dynamic_links

    second_report = import_services_from_config(
        "recording", path=store, config_path=config_path
    )
    assert second_report == {"added": 0, "skipped": 3, "errors": []}


def test_import_services_from_config_reports_urls_without_sample(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    config_path = tmp_path / "config.toml"
    _config_toml(
        config_path,
        "https://grafana.example.local/d/example/find-call-in-logs?orgId=000",
        "https://dashboards.example.local/app/data-explorer/discover#?_a=(metadata:(indexPattern:sip-stack-example,view:discover))",
        "",
    )

    report = import_services_from_config(
        "recording", path=store, config_path=config_path
    )

    assert report["added"] == 0
    assert len(report["errors"]) == 2
    assert any("find-call-in-logs" in item for item in report["errors"])
    assert list_sources(path=store) == []


def test_v1_source_without_replacements_uses_stored_strategy(tmp_path):
    store = tmp_path / "diagnostic_sources.json"
    source = validate_source(values())
    legacy = {key: value for key, value in source.items() if key != "replacements"}
    legacy.setdefault("id", "legacy0001")
    store.write_text(
        json.dumps({"version": 1, "managed_products": ["recording"], "sources": [legacy]}),
        encoding="utf-8",
    )

    groups = product_groups(path=store)

    names = [
        item["name"]
        for group in groups
        for level in group["levels"]
        for item in level["sources"]
    ]
    assert names == ["Пользовательский BFF"]


def test_source_without_replacements_and_strategy_raises_value_error(tmp_path):
    from core.dynamic_sources import _source_slots

    source = validate_source(values())
    legacy = {
        key: value
        for key, value in source.items()
        if key not in {"replacements", "strategy", "match_value"}
    }
    # из ссылки удалён номер — автодетект невозможен, а strategy нет
    legacy["example_url"] = "https://dashboards.example.local/discover#?_a=(view:discover)"
    legacy["sample_value"] = ""

    with pytest.raises(ValueError, match="значение-пример"):
        _source_slots(legacy)


def test_now_range_overrides_event_window_for_opensearch():
    source = validate_source(values(range_from="now-5d", range_to="now"))
    ctx = context()  # в заявке есть время события — должно игнорироваться

    (link,) = build_source_links(source, ctx)

    assert "from:'now-5d'" in link and "to:'now'" in link
    assert "2026-09-03" not in link


def test_now_range_overrides_event_window_for_grafana_dashboard():
    source = validate_source(
        values(
            example_url=grafana_dashboard_phone_pair(),
            sample_value="",
            range_from="Now-2H",
            range_to="NOW",
        )
    )
    ctx = context()

    (link,) = build_source_links(source, ctx)
    query = parse_qs(urlsplit(link).query, keep_blank_values=True)

    assert query["from"] == ["now-2h"]
    assert query["to"] == ["now"]


def test_now_range_validation():
    with pytest.raises(ValueError, match="обе границы"):
        validate_source(values(range_from="now-5d"))
    with pytest.raises(ValueError, match="ожидается now"):
        validate_source(values(range_from="сейчас", range_to="now"))
    with pytest.raises(ValueError, match="ожидается now"):
        validate_source(values(range_from="now-5", range_to="now"))
    with pytest.raises(ValueError, match="Explore"):
        validate_source(
            values(
                level="uuid",
                sample_value=CALL_UUID,
                range_from="now-5d",
                range_to="now",
                example_url=grafana_url(),
            )
        )


def test_single_slot_links_are_labeled_per_number():
    source = validate_source(values())
    ctx = context(phone="79157771575", phone_b="79209264847")

    labeled = build_source_links_labeled(source, ctx)

    # msisdn = phone_a (context-хелпер): дубль значения сворачивается
    labels = [label for _url, label in labeled]
    assert labels == ["клиент 79157771575", "номер Б 79209264847"]
