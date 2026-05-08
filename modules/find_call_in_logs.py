from urllib.parse import urlencode, quote_plus

from core.time_windows import event_datetimes, utc_window

BASE = "https://grafana.example.local/d/example-dashboard/find-call-in-logs"


def select_phones(ctx):
    phones = []

    for field in ("phone_a", "msisdn", "phone_b"):
        phone = ctx.get(field)
        if phone and phone not in phones:
            phones.append(phone)

    return (
        phones[0] if phones else "",
        phones[1] if len(phones) > 1 else "",
    )


def build_one(ctx, event_time=None):
    phone, second_phone = select_phones(ctx)

    params = {
        "orgId": "263",
        "timezone": "Europe/Moscow",

        "var-phone": phone,
        "var-second_phone": second_phone,

        "var-call_id": "",
        "var-nats_msg_id": "",
        "var-record_id": "",
        "var-transcription_id": "",
        "var-workflow_id": "",

        "var-env": "prod",
        "var-env_cluster": "prod",
    }

    if event_time:
        params["from"], params["to"] = utc_window(ctx, event_time)

    return f"{BASE}?{urlencode(params, quote_via=quote_plus)}"


def build(ctx):
    values = event_datetimes(ctx)

    if values:
        return [build_one(ctx, event_time) for event_time in values]

    return [build_one(ctx)]
