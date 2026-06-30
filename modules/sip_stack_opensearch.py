from urllib.parse import quote_plus

from core.config import opensearch_base_url, opensearch_index_pattern

SEARCH_PERIOD = ("now-1M", "now")


def msisdn_query(msisdn):
    if msisdn.startswith("7"):
        return f"*{msisdn[1:]}"

    return f"*{msisdn}"


def build_one(ctx, time_from, time_to):
    msisdn = ctx.get("msisdn")

    if not msisdn:
        return None

    query = quote_plus(f"'{msisdn_query(msisdn)}'")

    url = (
        f"{opensearch_base_url()}#"
        f"?_a=(discover:(columns:!(message),isDirty:!f,sort:!()),"
        f"metadata:(indexPattern:{opensearch_index_pattern('sip_stack')},view:discover))"
        f"&_g=(filters:!(),refreshInterval:(pause:!t,value:0),"
        f"time:(from:{time_from},to:{time_to}))"
        f"&_q=(filters:!(),query:(language:kuery,query:{query}))"
    )

    return url


def build(ctx):
    url = build_one(ctx, *SEARCH_PERIOD)

    return [url] if url else []
