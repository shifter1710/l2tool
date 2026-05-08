from datetime import timedelta
from zoneinfo import ZoneInfo


def event_datetimes(ctx):
    values = ctx.get("event_datetimes") or []

    if not values and ctx.get("event_time"):
        values = [ctx["event_time"]]

    return values


def fmt_utc(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def utc_window(ctx, event_time):
    local = event_time.replace(tzinfo=ZoneInfo(ctx["tz"]))
    utc = local.astimezone(ZoneInfo("UTC"))
    window = timedelta(minutes=ctx.get("window", 60))

    return fmt_utc(utc - window), fmt_utc(utc + window)
