from core.utils import hash_phone
from services.opensearch import build_discover_url

SEARCH_PERIOD = ("now-7d", "now")


def build_one(ctx, time_from, time_to):
    phone = ctx.get("msisdn") or ctx.get("phone_a") or ctx.get("phone_b")

    if not phone:
        return None

    return build_discover_url(
        "bff",
        legacy_index_name="bff",
        columns=(
            "request_id",
            "operation_id",
            "auth.msisdn",
            "auth.profile_id",
            "request.offset_timestamp",
            "response.total",
            "response.calls",
            "request.offset",
        ),
        query=f'"{hash_phone(phone)}"',
        time_from=time_from,
        time_to=time_to,
        is_dirty=True,
    )


def build(ctx):
    url = build_one(ctx, *SEARCH_PERIOD)

    return [url] if url else []
