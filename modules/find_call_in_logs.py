from datetime import timedelta
from urllib.parse import urlencode, quote_plus
from zoneinfo import ZoneInfo

BASE = "https://grafana.obs.mts.ru/d/feoiotv7dw9a8e/find-call-in-logs"


def fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def build(ctx):
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

    if ctx.get("event_time"):
        local = ctx["event_time"].replace(tzinfo=ZoneInfo(ctx["tz"]))
        utc = local.astimezone(ZoneInfo("UTC"))
        params["from"] = fmt(utc - timedelta(minutes=ctx.get("window", 60)))
        params["to"] = fmt(utc + timedelta(minutes=ctx.get("window", 60)))

    return [f"{BASE}?{urlencode(params, quote_via=quote_plus)}"]
