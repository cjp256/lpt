import logging
from typing import Dict, List, Set, Tuple

from .systemd import Service, Systemd

logger = logging.getLogger("lpt.graph")


def walk_dependencies(
    service_name: str,
    *,
    filter_services: List[str],
    filter_conditional_result_no: bool = False,
    filter_inactive: bool = True,
) -> Set[Tuple[Service, Service]]:
    deps = set()
    seen = set()
    service_cache: Dict[str, Service] = {}

    def _walk_dependencies(service_name: str) -> None:
        if service_name in seen:
            return
        seen.add(service_name)

        service = Service.query(service_name)
        if service is None:
            return

        service_cache[service_name] = service
        for dep_name in service.after:
            if dep_name in service_cache:
                service_dep = service_cache[dep_name]
            else:
                service_dep = Service.query(dep_name)
                service_cache[dep_name] = service_dep

            if dep_name in filter_services:
                continue

            if filter_conditional_result_no and not service_dep.condition_result:
                continue

            if filter_inactive and not service_dep.active_enter_timestamp_monotonic:
                continue

            deps.add((service, service_dep))
            _walk_dependencies(dep_name)

    _walk_dependencies(service_name)
    return deps


def generate_dependency_digraph(
    name: str,
    dependencies: Set[Tuple[Service, Service]],
) -> str:
    systemd = Systemd.query()

    def _label_svc(service: Service) -> str:
        label = f"{service.name} ("
        if service.time_to_activate:
            label += f"+{service.time_to_activate:.02f}s "

        service_start = service.calculate_relative_time_of_activation(
            systemd.userspace_timestamp_monotonic
        )
        label += f"@{service_start:.02f}s)"
        return label

    edges = set()
    for s1, s2 in sorted(dependencies, key=lambda x: x[0].name):
        label_s1 = _label_svc(s1)
        label_s2 = _label_svc(s2)
        edges.add(f'  "{label_s1}"->"{label_s2}" [color="green"];')

    lines = [f'digraph "{name}" {{', "  rankdir=LR;", *sorted(edges), "}"]
    return "\n".join(lines)
