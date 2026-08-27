from dataclasses import dataclass
from types import ModuleType

from modules import (
    attached_call_myconnect,
    bff_logs_opensearch,
    find_call_in_logs,
    profile_not_found_myconnect,
    recording_collector,
    recording_crs,
    recording_mgw,
    recording_vss_crs,
    sip_stack_opensearch,
)


@dataclass(frozen=True)
class ServiceDefinition:
    title: str
    platform: str
    module: ModuleType


SERVICES: dict[str, ServiceDefinition] = {
    "zapis": ServiceDefinition(
        title="Grafana / find-call-in-logs",
        platform="grafana",
        module=find_call_in_logs,
    ),
    "sip_stack": ServiceDefinition(
        title="SIP stack / OpenSearch",
        platform="opensearch",
        module=sip_stack_opensearch,
    ),
    "bff": ServiceDefinition(
        title="BFF / OpenSearch",
        platform="opensearch",
        module=bff_logs_opensearch,
    ),
    "myconnect": ServiceDefinition(
        title="MyConnect / OpenSearch",
        platform="opensearch",
        module=profile_not_found_myconnect,
    ),
    "myconnect_call": ServiceDefinition(
        title="MyConnect call / OpenSearch",
        platform="opensearch",
        module=attached_call_myconnect,
    ),
    "recording_mgw": ServiceDefinition(
        title="Запись / MGW / Loki",
        platform="grafana",
        module=recording_mgw,
    ),
    "recording_vss_crs": ServiceDefinition(
        title="Запись / VSS / Loki",
        platform="grafana",
        module=recording_vss_crs,
    ),
    "recording_crs": ServiceDefinition(
        title="Запись / CRS / Loki",
        platform="grafana",
        module=recording_crs,
    ),
    "recording_collector": ServiceDefinition(
        title="Запись / Collector / Loki",
        platform="grafana",
        module=recording_collector,
    ),
}


def service_modules() -> dict[str, ModuleType]:
    return {name: service.module for name, service in SERVICES.items()}


def service_titles() -> dict[str, str]:
    return {name: service.title for name, service in SERVICES.items()}
