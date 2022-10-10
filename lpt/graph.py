import dataclasses
import logging
import subprocess
from typing import Dict, FrozenSet, Optional, Set, Tuple

logger = logging.getLogger("lpt.graph")


@dataclasses.dataclass(frozen=True, eq=True)
class Service:
    name: str
    afters: FrozenSet[str]
    time_to_activate: Optional[float]
    active_enter_timestamp_monotonic: Optional[float]
    inactive_exit_timestamp_monotonic: Optional[float]
    exec_main_start_timestamp_monotonic: Optional[float]
    exec_main_exit_timestamp_monotonic: Optional[float]

    def is_valid(self) -> bool:
        return bool(
            self.inactive_exit_timestamp_monotonic
            or self.active_enter_timestamp_monotonic
        )

    @classmethod
    def query(cls, service_name: str) -> "Service":
        afters: FrozenSet[str] = frozenset()
        active_enter_timestamp_monotonic: Optional[float] = None
        inactive_exit_timestamp_monotonic: Optional[float] = None
        exec_main_start_timestamp_monotonic: Optional[float] = None
        exec_main_exit_timestamp_monotonic: Optional[float] = None
        time_to_activate: float = 0.0

        try:
            proc = subprocess.run(
                ["systemctl", "show", "--", service_name],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            logger.error("failed to show service=%s (error=%r)", service_name, error)
            raise

        lines = proc.stdout.strip().splitlines()
        for line in lines:
            line = line.strip()

            field = "After="
            if line.startswith(field):
                field_len = len(field)
                line = line[field_len:]
                afters = frozenset(line.split())

            field = "ActiveEnterTimestampMonotonic="
            if line.startswith(field):
                field_len = len(field)
                line = line[field_len:]
                active_enter_timestamp_monotonic = float(line) / 1000000

            field = "InactiveExitTimestampMonotonic="
            if line.startswith(field):
                field_len = len(field)
                line = line[field_len:]
                inactive_exit_timestamp_monotonic = float(line) / 1000000

            field = "ExecMainExitTimestampMonotonic="
            if line.startswith(field):
                field_len = len(field)
                line = line[field_len:]
                exec_main_exit_timestamp_monotonic = float(line) / 1000000

            field = "ExecMainStartTimestampMonotonic="
            if line.startswith(field):
                field_len = len(field)
                line = line[field_len:]
                exec_main_start_timestamp_monotonic = float(line) / 1000000

        if active_enter_timestamp_monotonic and inactive_exit_timestamp_monotonic:
            time_to_activate = (
                active_enter_timestamp_monotonic - inactive_exit_timestamp_monotonic
            )
        elif exec_main_exit_timestamp_monotonic and exec_main_start_timestamp_monotonic:
            time_to_activate = (
                exec_main_exit_timestamp_monotonic - exec_main_start_timestamp_monotonic
            )

        return cls(
            name=service_name,
            afters=afters,
            active_enter_timestamp_monotonic=active_enter_timestamp_monotonic,
            inactive_exit_timestamp_monotonic=inactive_exit_timestamp_monotonic,
            exec_main_start_timestamp_monotonic=exec_main_start_timestamp_monotonic,
            exec_main_exit_timestamp_monotonic=exec_main_exit_timestamp_monotonic,
            time_to_activate=time_to_activate,
        )


def walk_dependencies(
    service_name: str, services: Dict[str, Service]
) -> Set[Tuple[Service, Service]]:
    deps = set()
    seen = set()

    def _walk_dependencies(service_name: str) -> None:
        if service_name in seen:
            return
        seen.add(service_name)

        service = Service.query(service_name)
        if service is None:
            return

        services[service_name] = service
        for dep_name in service.afters:
            if dep_name in services:
                service_dep = services[dep_name]
            else:
                service_dep = Service.query(dep_name)
                services[dep_name] = service_dep

            deps.add((service, service_dep))
            _walk_dependencies(dep_name)

    _walk_dependencies(service_name)
    return deps


def generate_dependency_digraph(service_name: str) -> str:
    services: Dict[str, Service] = {}
    deps = walk_dependencies(service_name, services)

    def _label_svc(service: Service) -> str:
        label = service.name
        if service.time_to_activate:
            label += f" +{service.time_to_activate * 100:.02f}ms"

        return label

    edges = set()
    for s1, s2 in sorted(deps, key=lambda x: x[0].name):
        label_s1 = _label_svc(s1)
        label_s2 = _label_svc(s2)
        edges.add(f'  "{label_s1}"->"{label_s2}" [color="green"];')

    lines = [f'digraph "{service_name}" {{', "  rankdir=LR;", *sorted(edges), "}"]
    return "\n".join(lines)
