from core.config import grafana_recording_loki_datasource_uid, service_url
from services.loki_explore import build_explore_url_from_dashboard


def build_for_service(ctx, service_name, selector):
    call_uuid = ctx.get("call_uuid")
    if not call_uuid:
        raise ValueError("UUID записи не указан")
    return [
        build_explore_url_from_dashboard(
            service_url("zapis"),
            grafana_recording_loki_datasource_uid(),
            f'{selector} |= "{call_uuid}" | json',
        )
    ]
