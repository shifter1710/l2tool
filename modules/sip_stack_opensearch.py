from services.opensearch import build_discover_url

SEARCH_PERIOD = ("now-1M", "now")


def msisdn_query(msisdn):
    if msisdn.startswith("7"):
        return f"*{msisdn[1:]}"

    return f"*{msisdn}"


def build_one(ctx, time_from, time_to):
    msisdn = ctx.get("msisdn")

    if not msisdn:
        return None

    return build_discover_url(
        "sip_stack",
        legacy_index_name="sip_stack",
        columns=("message",),
        query=f"'{msisdn_query(msisdn)}'",
        time_from=time_from,
        time_to=time_to,
    )


def build(ctx):
    url = build_one(ctx, *SEARCH_PERIOD)

    return [url] if url else []
