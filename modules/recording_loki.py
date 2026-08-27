from core.config import service_url
from services.loki_explore import build_explore_url


def build_for_service(ctx, service_name, selector):
    call_uuid = ctx.get("call_uuid")
    if not call_uuid:
        raise ValueError("UUID записи не указан")
    return [build_explore_url(service_url(service_name), f'{selector} |= "{call_uuid}" | json')]
