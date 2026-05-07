from core.utils import hash_phone
from urllib.parse import quote_plus

BASE = "https://dashboards.example.local/app/data-explorer/discover"


def build(ctx):
    time_from = "now-1M"
    time_to = "now"

    phone = ctx.get("msisdn") or ctx.get("phone_a") or ctx.get("phone_b") or ""

    query_value = hash_phone(phone) if phone else ""
    query = quote_plus(f'"{query_value}"')

    url = (
        f"{BASE}#"
        f"?_a=(discover:(columns:!(request_id,operation_id,auth.msisdn,auth.profile_id,"
        f"request.offset_timestamp,response.total,response.calls,request.offset),"
        f"isDirty:!t,sort:!()),"
        f"metadata:(indexPattern:bff-example,view:discover))"
        f"&_g=(filters:!(),refreshInterval:(pause:!t,value:0),"
        f"time:(from:{time_from},to:{time_to}))"
        f"&_q=(filters:!(),query:(language:kuery,query:{query}))"
    )

    return [url]
