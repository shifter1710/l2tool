from urllib.parse import quote_plus

BASE = "https://dashboards.example.local/app/data-explorer/discover"
OPEN_IN_CHROME = True


def select_other_phone(msisdn, phone_a, phone_b):
    if phone_a == msisdn and phone_b:
        return phone_b

    if phone_b == msisdn and phone_a:
        return phone_a

    return None


def build_query(msisdn, phone_a, phone_b):
    master = f'"master:{msisdn}"'
    other_phone = select_other_phone(msisdn, phone_a, phone_b)

    if other_phone:
        return f'{master} AND "sip:+{other_phone}"'

    sip_terms = [f'"sip:+{phone}"' for phone in (phone_a, phone_b) if phone]
    if sip_terms:
        return f"{master} AND ({' OR '.join(sip_terms)})"

    return master


def build(ctx):
    msisdn = ctx.get("msisdn")
    phone_a = ctx.get("phone_a")
    phone_b = ctx.get("phone_b")

    if not msisdn:
        print("[WARN] attached_call_myconnect: msisdn not found, skip")
        return []

    query = quote_plus(build_query(msisdn, phone_a, phone_b))

    url = (
        f"{BASE}#"
        f"?_a=(discover:(columns:!(rawData,message,params),isDirty:!f,sort:!()),"
        f"metadata:(indexPattern:myconnect-example,view:discover))"
        f"&_g=(filters:!(),refreshInterval:(pause:!t,value:0),time:(from:now-2M,to:now))"
        f"&_q=(filters:!(),query:(language:kuery,query:'{query}'))"
    )

    return [url]
