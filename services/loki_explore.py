import json
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit


def _replace_query(node, expression):
    if isinstance(node, dict):
        return {
            key: expression if key == "expr" else _replace_query(value, expression)
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_replace_query(value, expression) for value in node]
    return node


def build_explore_url(url, expression):
    """Replace Loki expressions in a copied Grafana Explore URL."""
    if not url:
        raise ValueError("Grafana Explore URL is not configured")

    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    updated = False
    for key in ("panes", "left"):
        if key not in params:
            continue
        try:
            params[key] = json.dumps(
                _replace_query(json.loads(params[key]), expression),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except json.JSONDecodeError as error:
            raise ValueError(f"Cannot parse Grafana Explore parameter: {key}") from error
        updated = True

    if not updated:
        raise ValueError("Copied Grafana Explore URL must contain panes or left")

    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(params, quote_via=quote_plus), parts.fragment)
    )
