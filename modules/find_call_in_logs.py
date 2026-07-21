from urllib.parse import urlencode, quote_plus

from core.config import grafana_env, grafana_env_cluster, grafana_find_call_dashboard, grafana_org_id
from core.time_windows import event_datetimes, utc_day_window, utc_range, utc_window


def phone_without_country_code(phone):
    if (
        isinstance(phone, str)
        and len(phone) == 11
        and phone.startswith("7")
        and phone.isdigit()
    ):
        return phone[1:]

    return phone


def select_phones(ctx):
    phones = []

    for field in ("phone_a", "msisdn", "phone_b"):
        phone = ctx.get(field)
        if not phone:
            continue

        phone = phone_without_country_code(phone)
        if phone not in phones:
            phones.append(phone)

    return (
        phones[0] if phones else "",
        phones[1] if len(phones) > 1 else "",
    )


def phone_pairs(ctx):
    client = phone_without_country_code(ctx.get("msisdn"))
    participants = []
    for field in ("phone_a_values", "phone_b_values"):
        for phone in ctx.get(field) or []:
            normalized = phone_without_country_code(phone)
            if normalized and normalized != client and normalized not in participants:
                participants.append(normalized)

    if len(participants) > 1:
        return [(participant, client or "") for participant in participants]

    if participants and ctx.get("phone_a_partial") and client:
        return [(client, participants[0])]

    return [select_phones(ctx)]


def build_one(ctx, event_time=None, phones=None):
    phone, second_phone = phones or select_phones(ctx)

    params = {
        "orgId": grafana_org_id(),
        "timezone": ctx.get("tz", "Europe/Moscow"),

        "var-phone": phone,
        "var-second_phone": second_phone,

        "var-call_id": "",
        "var-nats_msg_id": "",
        "var-record_id": "",
        "var-transcription_id": "",
        "var-workflow_id": "",

        "var-env": grafana_env(),
        "var-env_cluster": grafana_env_cluster(),
    }

    if ctx.get("event_time_range"):
        params["from"], params["to"] = utc_range(ctx, ctx["event_time_range"])
    elif event_time:
        params["from"], params["to"] = utc_window(ctx, event_time)
    elif ctx.get("event_date") and not ctx.get("event_time"):
        day_window = utc_day_window(ctx)
        if day_window:
            params["from"], params["to"] = day_window

    return f"{grafana_find_call_dashboard()}?{urlencode(params, quote_via=quote_plus)}"


def build(ctx):
    pairs = phone_pairs(ctx)

    if ctx.get("event_time_range"):
        return [build_one(ctx, phones=phones) for phones in pairs]

    values = event_datetimes(ctx)

    if values:
        return [
            build_one(ctx, event_time, phones=phones)
            for phones in pairs
            for event_time in values
        ]

    return [build_one(ctx, phones=phones) for phones in pairs]
