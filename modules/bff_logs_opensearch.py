from urllib.parse import quote_plus

from core.config import opensearch_base_url, opensearch_index_pattern
from core.utils import hash_phone

SEARCH_PERIOD = ("now-1M", "now")


def build_one(ctx, time_from, time_to):
    phone = ctx.get("msisdn") or ctx.get("phone_a") or ctx.get("phone_b")

    if not phone:
        return None

    query_value = hash_phone(phone)
    query = quote_plus(f'"{query_value}"')

    url = (
        f"{opensearch_base_url()}#"
        f"?_a=(discover:(columns:!(request_id,operation_id,auth.msisdn,auth.profile_id,"
        f"request.offset_timestamp,response.total,response.calls,request.offset),"
        f"isDirty:!t,sort:!()),"
        f"metadata:(indexPattern:{opensearch_index_pattern('bff')},view:discover))"
        f"&_g=(filters:!(),refreshInterval:(pause:!t,value:0),"
        f"time:(from:{time_from},to:{time_to}))"
        f"&_q=(filters:!(),query:(language:kuery,query:{query}))"
    )

    return url


def build(ctx):
    url = build_one(ctx, *SEARCH_PERIOD)

    return [url] if url else []
