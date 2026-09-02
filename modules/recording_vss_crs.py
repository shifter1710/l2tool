from modules.recording_loki import build_for_service

REQUIRES_CALL_UUID = True


def build(ctx):
    return build_for_service(ctx, '{unit="vss.service"}')
