from urllib.parse import urlencode, quote_plus

from core.config import grafana_env, grafana_env_cluster, grafana_find_call_dashboard, grafana_org_id
from core.time_windows import event_datetimes, utc_day_window, utc_window


def phone_without_country_code(phone):
    if len(phone) == 11 and phone.startswith("7"):
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


def build_one(ctx, event_time=None):
    phone, second_phone = select_phones(ctx)

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

    if event_time:
        params["from"], params["to"] = utc_window(ctx, event_time)
    elif ctx.get("event_date") and not ctx.get("event_time"):
        day_window = utc_day_window(ctx)
        if day_window:
            params["from"], params["to"] = day_window

    return f"{grafana_find_call_dashboard()}?{urlencode(params, quote_via=quote_plus)}"


def build(ctx):
    values = event_datetimes(ctx)

    if values:
        return [build_one(ctx, event_time) for event_time in values]

    return [build_one(ctx)]
