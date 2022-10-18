import logging
from typing import List, Set, Tuple

from .cloudinit import CloudInitService
from .systemd import Service

logger = logging.getLogger("lpt.graph")


def generate_dependency_digraph(
    name: str,
    *,
    systemd_service_dependencies: Set[Tuple[Service, Service]],
    cloud_init_services: List[CloudInitService],
) -> str:
    edges = set()

    for s1, s2 in sorted(systemd_service_dependencies, key=lambda x: x[0].name):
        label_s1 = s1.get_label()
        label_s2 = s2.get_label()
        edges.add(f'  "{label_s1}"->"{label_s2}" [color="green"];')

    # Add cloud-init frames.
    for s1, _ in sorted(systemd_service_dependencies, key=lambda x: x[0].name):
        mappings = {
            "cloud-init-local.service": "init-local",
            "cloud-init.service": "init-network",
            "cloud-config.service": "modules-config",
            "cloud-final.service": "modules-final",
        }
        stage = mappings.pop(s1.name, None)
        if not stage:
            continue

        label_s1 = s1.get_label()
        for service_frame in list(cloud_init_services):
            if service_frame.stage != stage:
                continue

            label_s2 = service_frame.get_label()
            edges.add(f'  "{label_s1}"->"{label_s2}" [color="green"];')
            cloud_init_services.remove(service_frame)

    lines = [f'digraph "{name}" {{', "  rankdir=LR;", *sorted(edges), "}"]
    return "\n".join(lines)
