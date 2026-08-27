from urllib.parse import quote_plus

from services.opensearch import build_discover_url, resolve_target

FIXED_FILTER = "failed starting call on IMS side: profile not found"
SEARCH_PERIOD = ("now-2M", "now")


def build_one(ctx, time_from, time_to):
    msisdn = ctx.get("msisdn")

    if not msisdn:
        return None

    query = msisdn
    phrase = quote_plus(FIXED_FILTER)
    index_pattern = resolve_target("myconnect", "myconnect").index_pattern
    filters = (
        f"!(('$state':(store:appState),meta:(alias:!n,disabled:!f,"
        f"index:{index_pattern},key:message,negate:!f,"
        f"params:(query:'{phrase}'),type:phrase),"
        f"query:(match_phrase:(message:'{phrase}'))))"
    )
    return build_discover_url(
        "myconnect",
        legacy_index_name="myconnect",
        columns=("rawData", "message", "params"),
        query=query,
        time_from=time_from,
        time_to=time_to,
        filters=filters,
        quote_query=True,
    )


def build(ctx):
    url = build_one(ctx, *SEARCH_PERIOD)

    return [url] if url else []
