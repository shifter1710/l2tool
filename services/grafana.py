from collections.abc import Mapping
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit


def merge_dashboard_params(
    dashboard_url: str,
    params: Mapping[str, object],
) -> str:
    if not dashboard_url:
        raise ValueError("Grafana dashboard URL is not configured")

    parts = urlsplit(dashboard_url)
    merged_params = dict(parse_qsl(parts.query, keep_blank_values=True))
    merged_params.update(
        {key: str(value) for key, value in params.items() if value is not None}
    )
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(merged_params, quote_via=quote_plus),
            parts.fragment,
        )
    )
