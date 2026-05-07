from urllib.parse import quote_plus
from datetime import timedelta
from zoneinfo import ZoneInfo
from core.utils import hash_phone

BASE = "https://dashboards.obs.mts.ru/app/data-explorer/discover"


def fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build(ctx):
    local = ctx["event_time"].replace(tzinfo=ZoneInfo(ctx["tz"]))
    utc = local.astimezone(ZoneInfo("UTC"))

    window = ctx.get("window", 60)

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
        f"metadata:(indexPattern:dialer-dmz-internet,view:discover))"
        f"&_g=(filters:!(),refreshInterval:(pause:!t,value:0),"
        f"time:(from:{time_from},to:{time_to}))"
        f"&_q=(filters:!(),query:(language:kuery,query:{query}))"
    )

    return [url]