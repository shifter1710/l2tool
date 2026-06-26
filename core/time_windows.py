from datetime import datetime, time, timedelta
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


def utc_day_window(ctx):
    event_date = ctx.get("event_date")
    if not event_date:
        return None

    tz = ZoneInfo(ctx["tz"])
    start = datetime.combine(event_date, time.min, tzinfo=tz).astimezone(ZoneInfo("UTC"))
    end = datetime.combine(event_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(ZoneInfo("UTC"))

    return fmt_utc(start), fmt_utc(end)
