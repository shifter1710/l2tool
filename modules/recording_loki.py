from core.config import grafana_recording_loki_datasource_uid, service_url
from core.time_windows import utc_search_windows
from core.utils import normalize_uuid
from services.loki_explore import build_explore_url_from_dashboard


def build_for_service(ctx, selector):
    call_uuid = ctx.get("call_uuid")
    if not call_uuid:
        raise ValueError("UUID записи не указан")
    call_uuid = normalize_uuid(call_uuid)

    windows = utc_search_windows(ctx) or [("now-1h", "now")]
    return [
        build_explore_url_from_dashboard(
            service_url("zapis"),
            grafana_recording_loki_datasource_uid(),
            f'{selector} |= "{call_uuid}" | json',
            time_from=time_from,
            time_to=time_to,
        )
        for time_from, time_to in windows
    ]
