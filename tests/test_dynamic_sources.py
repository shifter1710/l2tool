import json
import stat
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import pytest

from core.dynamic_sources import (
    build_source_links,
    delete_source,
    import_sources,
    is_managed,
    list_sources,
    product_groups,
    save_source,
    validate_source,
)
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
        (None, None, "79991234567", "9991234567", "9991234567"),
        ("79209264847", None, "79157771575", "9209264847", "9157771575"),
        (None, "79209264847", "79157771575", "9157771575", "9209264847"),
    ],
)
def test_two_phone_slots_fall_back_to_client_number(
    phone_a, phone_b, client, expected_a, expected_b
):
    source = validate_source(
        values(example_url=grafana_dashboard_phone_pair(), sample_value="")
    )
    ctx = context(phone=phone_a, phone_b=phone_b, client=client)
    ctx["phone_a"] = phone_a
    link = build_source_links(source, ctx)[0]
    query = parse_qs(urlsplit(link).query)

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
