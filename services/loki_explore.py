import json
import re
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

_PHONE_FILTER = re.compile(r"(?P<prefix>\|=\s*)`\+?\d{10,11}`")


def _transform_query(node, transform):
    if isinstance(node, dict):
        return {
            key: (
                transform(value)
                if key == "expr" and isinstance(value, str)
                else _transform_query(value, transform)
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_transform_query(value, transform) for value in node]
    return node


def _replace_time_range(node, time_from, time_to):
    replaced = 0

    if isinstance(node, dict):
        updated = {}
        for key, value in node.items():
            transformed, count = _replace_time_range(value, time_from, time_to)
            updated[key] = transformed
            replaced += count

        if isinstance(updated.get("range"), dict):
            updated["range"] = {
                **updated["range"],
                "from": time_from,
                "to": time_to,
            }
            replaced += 1
        return updated, replaced

    if isinstance(node, list):
        updated = []
        for value in node:
            transformed, count = _replace_time_range(value, time_from, time_to)
            updated.append(transformed)
            replaced += count
        return updated, replaced

    return node, replaced


def _build_explore_url(url, transform, *, time_from=None, time_to=None):
    if not url:
        raise ValueError("Grafana Explore URL is not configured")

    if (time_from is None) != (time_to is None):
        raise ValueError("Both Grafana Explore time boundaries must be provided")

    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    updated = False
    range_replaced = False
    for key in ("panes", "left"):
        if key not in params:
            continue
        try:
            state = _transform_query(json.loads(params[key]), transform)
            if time_from is not None:
                state, replacement_count = _replace_time_range(
                    state,
                    time_from,
                    time_to,
                )
                range_replaced = range_replaced or bool(replacement_count)
            params[key] = json.dumps(
                state,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except json.JSONDecodeError as error:
            raise ValueError(f"Cannot parse Grafana Explore parameter: {key}") from error
        updated = True

    if not updated:
        raise ValueError("Copied Grafana Explore URL must contain panes or left")
    if time_from is not None and not range_replaced:
        raise ValueError("Copied Grafana Explore URL must contain a time range")

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(params, quote_via=quote_plus),
            parts.fragment,
        )
    )


def build_explore_url(url, expression):
    """Replace Loki expressions in a copied Grafana Explore URL."""
    return _build_explore_url(url, lambda _current: expression)


def build_phone_explore_url(url, phone, *, time_from=None, time_to=None):
    """Replace the first backtick-quoted phone filter in a copied Explore URL."""
    replaced = False

    def replace_phone(expression):
        nonlocal replaced
        updated, count = _PHONE_FILTER.subn(
            lambda match: f'{match.group("prefix")}`{phone}`',
            expression,
            count=1,
        )
        replaced = replaced or bool(count)
        return updated

    result = _build_explore_url(
        url,
        replace_phone,
        time_from=time_from,
        time_to=time_to,
    )
    if not replaced:
        raise ValueError(
            "Copied Grafana Explore URL must contain a phone filter in backticks"
        )
    return result


def build_explore_url_from_dashboard(
    dashboard_url,
    datasource_uid,
    expression,
    *,
    time_from="now-1h",
    time_to="now",
):
    if not dashboard_url:
        raise ValueError("Grafana dashboard URL is not configured for service: zapis")
    if not datasource_uid:
        raise ValueError("Grafana Loki datasource UID is not configured")

    dashboard = urlsplit(dashboard_url)
    org_id = dict(parse_qsl(dashboard.query)).get("orgId")
    if not org_id:
        raise ValueError("Grafana dashboard URL must contain orgId")

    pane = {
        "datasource": datasource_uid,
        "queries": [
            {
                "refId": "A",
                "expr": expression,
                "queryType": "range",
                "datasource": {"type": "loki", "uid": datasource_uid},
                "editorMode": "code",
                "direction": "backward",
            }
        ],
        "range": {"from": time_from, "to": time_to},
        "panelsState": {"logs": {"visualisationType": "logs"}},
    }
    params = {
        "schemaVersion": "1",
        "panes": json.dumps({"A": pane}, separators=(",", ":")),
        "orgId": org_id,
    }
    explore_url = urlencode(params, quote_via=quote_plus)
    return urlunsplit((dashboard.scheme, dashboard.netloc, "/explore", explore_url, ""))
