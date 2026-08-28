import re
from dataclasses import dataclass
from urllib.parse import quote_plus, unquote, urlsplit, urlunsplit

from core.config import (
    opensearch_base_url,
    opensearch_index_pattern,
    service_index_pattern,
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
    quote_query: bool = False,
) -> str:
    target = resolve_target(service_name, legacy_index_name)
    encoded_query = quote_plus(query)
    query_value = f"'{encoded_query}'" if quote_query else encoded_query
    dirty_value = "!t" if is_dirty else "!f"
    columns_value = ",".join(columns)

    return (
        f"{target.base_url}#"
        f"?_a=(discover:(columns:!({columns_value}),isDirty:{dirty_value},sort:!()),"
        f"metadata:(indexPattern:{target.index_pattern},view:discover))"
        f"&_g=(filters:!(),refreshInterval:(pause:!t,value:0),"
        f"time:(from:'{time_from}',to:'{time_to}'))"
        f"&_q=(filters:{filters},query:(language:kuery,query:{query_value}))"
    )
