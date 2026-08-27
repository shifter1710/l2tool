from modules.recording_loki import build_for_service


def build(ctx):
    return build_for_service(ctx, "recording_explore", '{unit="vss.service"}')
