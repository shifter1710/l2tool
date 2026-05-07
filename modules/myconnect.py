from urllib.parse import quote_plus

BASE = "https://dashboards.obs.mts.ru/app/data-explorer/discover"

FIXED_FILTER = "failed starting call on IMS side: profile not found"


def build(ctx):
    msisdn = ctx.get("msisdn")

    if not msisdn:
        print("[WARN] myconnect: msisdn not found, skip")
        return []

    query = quote_plus(msisdn)
    phrase = quote_plus(FIXED_FILTER)

    url = (
        f"{BASE}#"
        f"?_a=(discover:(columns:!(rawData,message,params),isDirty:!f,sort:!()),"
        f"metadata:(indexPattern:myconnect-production,view:discover))"
        f"&_g=(filters:!(),refreshInterval:(pause:!t,value:0),time:(from:now-2M,to:now))"
        f"&_q=(filters:!(('$state':(store:appState),meta:(alias:!n,disabled:!f,"
        f"index:myconnect-production,key:message,negate:!f,"
        f"params:(query:'{phrase}'),type:phrase),"
        f"query:(match_phrase:(message:'{phrase}')))),"
        f"query:(language:kuery,query:'{query}'))"
    )

    return [url]