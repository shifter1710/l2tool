from core.time_windows import time_ranges
from urllib.parse import quote_plus

BASE = "https://dashboards.example.local/app/data-explorer/discover"

FIXED_FILTER = "failed starting call on IMS side: profile not found"
OPEN_IN_CHROME = True


def build_one(ctx, time_from, time_to):
    msisdn = ctx.get("msisdn")

    if not msisdn:
        print("[WARN] profile_not_found_myconnect: msisdn not found, skip")
        return None

    query = quote_plus(msisdn)
    phrase = quote_plus(FIXED_FILTER)

    url = (
        f"{BASE}#"
        f"?_a=(discover:(columns:!(rawData,message,params),isDirty:!f,sort:!()),"
        f"metadata:(indexPattern:myconnect-example,view:discover))"
        f"&_g=(filters:!(),refreshInterval:(pause:!t,value:0),time:(from:{time_from},to:{time_to}))"
        f"&_q=(filters:!(('$state':(store:appState),meta:(alias:!n,disabled:!f,"
        f"index:myconnect-example,key:message,negate:!f,"
        f"params:(query:'{phrase}'),type:phrase),"
        f"query:(match_phrase:(message:'{phrase}')))),"
        f"query:(language:kuery,query:'{query}'))"
    )

    return url


def build(ctx):
    urls = [
        build_one(ctx, time_from, time_to)
        for time_from, time_to in time_ranges(ctx, "now-2M", "now")
    ]

    return [url for url in urls if url]
