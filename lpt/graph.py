import logging
from typing import Dict, List, Set, Tuple

from .systemd import Service, Systemd, SystemdService

logger = logging.getLogger("lpt.graph")



def generate_dependency_digraph(
    name: str,
    dependencies: Set[Tuple[Service, Service]],
) -> str:
    systemd = Systemd.query()
    edges = set()

    print(systemd.userspace_timestamp_monotonic)

    for s1, s2 in sorted(dependencies, key=lambda x: x[0].name):
        label_s1 = s1.get_label(systemd.userspace_timestamp_monotonic)
        label_s2 = s2.get_label(systemd.userspace_timestamp_monotonic)
        edges.add(f'  "{label_s1}"->"{label_s2}" [color="green"];')

    lines = [f'digraph "{name}" {{', "  rankdir=LR;", *sorted(edges), "}"]
    return "\n".join(lines)
