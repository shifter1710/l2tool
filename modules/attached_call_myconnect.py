from services.opensearch import build_discover_url, configured_search_period

SEARCH_PERIOD = ("now-2M", "now")


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


def build_one(ctx, time_from, time_to):
    msisdn = ctx.get("msisdn")
    phone_a = ctx.get("phone_a")
    phone_b = ctx.get("phone_b")

    if not msisdn:
        return None

    return build_discover_url(
        "myconnect_call",
        legacy_index_name="myconnect",
        fallback_service_name="myconnect",
        columns=("rawData", "message", "params"),
        query=build_query(msisdn, phone_a, phone_b),
        time_from=time_from,
        time_to=time_to,
    )


def build(ctx):
    msisdn = ctx.get("msisdn")
    participants = []
    for field in ("phone_a_values", "phone_b_values"):
        for phone in ctx.get(field) or []:
            if phone and phone != msisdn and phone not in participants:
                participants.append(phone)

    if len(participants) > 1:
        return [
            build_one(
                {**ctx, "phone_a": participant, "phone_b": None},
                *configured_search_period("myconnect_call", SEARCH_PERIOD, ctx),
            )
            for participant in participants
        ]

    url = build_one(
        ctx,
        *configured_search_period("myconnect_call", SEARCH_PERIOD, ctx),
    )

    return [url] if url else []
