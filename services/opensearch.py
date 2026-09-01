import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from core.config import (
    opensearch_base_url,
    opensearch_index_pattern,
    service_index_pattern,
    service_minutes_after,
    service_minutes_before,
    service_url,
)


@dataclass(frozen=True)
class OpenSearchTarget:
    base_url: str
    index_pattern: str


_INDEX_PATTERN = re.compile(
    r"indexPattern:(?:'(?P<quoted>[^']+)'|(?P<plain>[^,)&]+))"
)


def extract_index_pattern(url: str) -> str | None:
    match = _INDEX_PATTERN.search(unquote(url))
    if not match:
        return None
    return (match.group("quoted") or match.group("plain")).strip()


def _without_fragment(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _rison_url_string(value: str) -> str:
    escaped = str(value).replace("!", "!!").replace("'", "!'")
    return f"'{quote(escaped, safe='')}'"


def configured_search_period(
    service_name: str,
    default: tuple[str, str],
    ctx: dict | None = None,
) -> tuple[str, str]:
    ctx = ctx or {}
    event_range = ctx.get("event_time_range")
    event_values = list(ctx.get("event_datetimes") or [])
    if not event_values and ctx.get("event_time"):
        event_values = [ctx["event_time"]]

    if event_range:
        start, end = event_range
    elif event_values:
        start, end = min(event_values), max(event_values)
    elif ctx.get("event_date"):
        start = datetime.combine(ctx["event_date"], time(hour=8))
        end = datetime.combine(ctx["event_date"], time(hour=20))
    else:
        return default

    source_tz = ZoneInfo(ctx.get("tz", "Europe/Moscow"))
    target_tz = ZoneInfo("Europe/Moscow")

    def to_moscow(value):
        if value.tzinfo is None:
            value = value.replace(tzinfo=source_tz)
        return value.astimezone(target_tz).replace(tzinfo=None)

    start = to_moscow(start) - timedelta(
        minutes=int(service_minutes_before(service_name))
    )
    end = to_moscow(end) + timedelta(
        minutes=int(service_minutes_after(service_name))
    )
    return (
        start.strftime("%Y-%m-%dT%H:%M:%S.000"),
        end.strftime("%Y-%m-%dT%H:%M:%S.000"),
    )


def resolve_target(service_name: str, legacy_index_name: str) -> OpenSearchTarget:
    configured_url = service_url(service_name)
    base_url = configured_url or opensearch_base_url()
    if not base_url:
        raise ValueError(f"OpenSearch URL is not configured for service: {service_name}")

    index_pattern = service_index_pattern(service_name)
    if not index_pattern and configured_url:
        index_pattern = extract_index_pattern(configured_url)
    if not index_pattern:
        index_pattern = opensearch_index_pattern(legacy_index_name)
    if not index_pattern:
        raise ValueError(
            f"OpenSearch indexPattern is not configured for service: {service_name}. "
            "Copy a Discover URL with the required data view into the service URL."
        )

    return OpenSearchTarget(
        base_url=_without_fragment(base_url),
        index_pattern=str(index_pattern),
    )


def build_discover_url(
    service_name: str,
    *,
    legacy_index_name: str,
    columns: tuple[str, ...],
    query: str,
    time_from: str,
    time_to: str,
    filters: str = "!()",
    is_dirty: bool = False,
) -> str:
    target = resolve_target(service_name, legacy_index_name)
    query_value = _rison_url_string(query)
    time_from_value = _rison_url_string(time_from)
    time_to_value = _rison_url_string(time_to)
    dirty_value = "!t" if is_dirty else "!f"
    columns_value = ",".join(columns)

    return (
        f"{target.base_url}#"
        f"?_a=(discover:(columns:!({columns_value}),isDirty:{dirty_value},sort:!()),"
        f"metadata:(indexPattern:{target.index_pattern},view:discover))"
        f"&_g=(filters:!(),refreshInterval:(pause:!t,value:0),"
        f"time:(from:{time_from_value},to:{time_to_value}))"
        f"&_q=(filters:{filters},query:(language:kuery,query:{query_value}))"
    )
