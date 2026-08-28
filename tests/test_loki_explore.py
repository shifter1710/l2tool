import json
from urllib.parse import parse_qs, urlsplit

from services.loki_explore import build_explore_url_from_dashboard


def test_explore_url_reuses_dashboard_host_and_org_id():
    url = build_explore_url_from_dashboard(
        "https://grafana.example.local/d/abc/dashboard?orgId=42&from=now-5m",
        "loki-example",
        '{unit="mgw\\.service"} |= "uuid-value" | json',
    )

    parts = urlsplit(url)
    params = parse_qs(parts.query)
    panes = json.loads(params["panes"][0])

    assert parts.netloc == "grafana.example.local"
    assert parts.path == "/explore"
    assert params["orgId"] == ["42"]
    assert panes["A"]["datasource"] == "loki-example"
    assert panes["A"]["queries"][0]["expr"] == (
        '{unit="mgw\\.service"} |= "uuid-value" | json'
    )


def test_explore_url_accepts_absolute_time_range():
    url = build_explore_url_from_dashboard(
        "https://grafana.example.local/d/abc/dashboard?orgId=42",
        "loki-example",
        '{unit="mgw\\.service"} |= "79990000000" | json',
        time_from="2026-08-01T09:00:00.000Z",
        time_to="2026-08-01T11:00:00.000Z",
    )

    panes = json.loads(parse_qs(urlsplit(url).query)["panes"][0])

    assert panes["A"]["range"] == {
        "from": "2026-08-01T09:00:00.000Z",
        "to": "2026-08-01T11:00:00.000Z",
    }
