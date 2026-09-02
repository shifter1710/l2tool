from core.config import service_url
from core.time_windows import utc_search_windows
from services.loki_explore import build_phone_explore_url


def build(ctx):
    phone = ctx.get("msisdn") or ctx.get("phone_a") or ctx.get("phone_b")
    if not phone:
        return []

    url = service_url("secretary")
    windows = utc_search_windows(ctx)
    if not windows:
        return [build_phone_explore_url(url, phone)]

    return [
        build_phone_explore_url(
            url,
            phone,
            time_from=time_from,
            time_to=time_to,
        )
        for time_from, time_to in windows
    ]
