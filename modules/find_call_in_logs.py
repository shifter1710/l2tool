from urllib.parse import urlencode, quote_plus

from core.time_windows import event_datetimes, utc_window

BASE = "https://grafana.example.local/d/example-dashboard/find-call-in-logs"


def build_one(ctx, event_time=None):
    params = {
        "orgId": "263",
        "timezone": "Europe/Moscow",

        "var-phone": ctx.get("phone_a") or ctx.get("msisdn") or "",
        "var-second_phone": ctx.get("phone_b") or "",

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
