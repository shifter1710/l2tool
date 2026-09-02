from core.config import service_url
from core.time_windows import utc_search_windows
from services.loki_explore import build_phone_explore_url


def _search_phone(phone):
    if len(phone) == 11 and phone.startswith("7"):
        return phone[1:]
    return phone


def build(ctx):
    phone = ctx.get("msisdn") or ctx.get("phone_a") or ctx.get("phone_b")
    if not phone:
        return []

    url = service_url("noise")
    phone = _search_phone(phone)
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
