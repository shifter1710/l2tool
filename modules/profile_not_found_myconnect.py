from urllib.parse import quote_plus

from core.config import opensearch_base_url, opensearch_index_pattern

FIXED_FILTER = "failed starting call on IMS side: profile not found"
SEARCH_PERIOD = ("now-2M", "now")


def build_one(ctx, time_from, time_to):
    msisdn = ctx.get("msisdn")

    if not msisdn:
        return None

    query = quote_plus(msisdn)
    phrase = quote_plus(FIXED_FILTER)
    index_pattern = opensearch_index_pattern("myconnect")

    url = (
        f"{opensearch_base_url()}#"
        f"?_a=(discover:(columns:!(rawData,message,params),isDirty:!f,sort:!()),"
        f"metadata:(indexPattern:{index_pattern},view:discover))"
        f"&_g=(filters:!(),refreshInterval:(pause:!t,value:0),time:(from:{time_from},to:{time_to}))"
        f"&_q=(filters:!(('$state':(store:appState),meta:(alias:!n,disabled:!f,"
        f"index:{index_pattern},key:message,negate:!f,"
        f"params:(query:'{phrase}'),type:phrase),"
        f"query:(match_phrase:(message:'{phrase}')))),"
        f"query:(language:kuery,query:'{query}'))"
    )

    return url


def build(ctx):
    url = build_one(ctx, *SEARCH_PERIOD)

    return [url] if url else []
