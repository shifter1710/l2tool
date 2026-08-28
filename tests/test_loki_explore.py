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
