import dataclasses
import datetime
import logging
import subprocess
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

logger = logging.getLogger("lpt.graph")


def convert_systemctl_timestamp(timestamp: str) -> datetime.datetime:
    return datetime.datetime.strptime(timestamp, "%a %Y-%m-%d %H:%M:%S %Z")


def convert_systemctl_timestamp_opt(timestamp: str) -> Optional[datetime.datetime]:
    if timestamp == "n/a":
        return None

    return convert_systemctl_timestamp(timestamp)


def convert_systemctl_monotonic(timestamp: str) -> float:
    return float(timestamp) / 1000000


def convert_systemctl_bool(value: str) -> bool:
    return not value == "no"


def query_systemctl_show(
    service_name: Optional[str] = None,
) -> Dict[str, str]:
    properties = {}

    cmd = ["systemctl", "show"]
    if service_name:
        cmd.extend(["--", service_name])
    try:
        logger.debug("Executing: %r", cmd)
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        logger.error("cmd (%r) failed (error=%r)", cmd, error)
        raise

    lines = proc.stdout.strip().splitlines()
    for line in lines:
        line = line.strip()
        try:
            key, value = line.split("=", 1)
        except ValueError:
            logger.debug("failed to parse: %r", line)
            continue

        properties[key] = value

    return properties


@dataclasses.dataclass(frozen=True, eq=True)
class Systemd:
    userspace_timestamp: datetime.datetime
    userspace_timestamp_monotonic: float
    finish_timestamp: datetime.datetime
    finish_timestamp_monotonic: float

    @classmethod
    def query(cls) -> "Systemd":
        properties = query_systemctl_show()

        userspace_timestamp = convert_systemctl_timestamp(
            properties["UserspaceTimestamp"]
        )
        userspace_timestamp_monotonic = convert_systemctl_monotonic(
            properties["UserspaceTimestampMonotonic"]
        )
        finish_timestamp = convert_systemctl_timestamp(properties["FinishTimestamp"])
        finish_timestamp_monotonic = convert_systemctl_monotonic(
            properties["FinishTimestampMonotonic"]
        )

        return cls(
            userspace_timestamp=userspace_timestamp,
            userspace_timestamp_monotonic=userspace_timestamp_monotonic,
            finish_timestamp=finish_timestamp,
            finish_timestamp_monotonic=finish_timestamp_monotonic,
        )


@dataclasses.dataclass(frozen=True, eq=True)
class Service:
    name: str
    after: FrozenSet[str]
    condition_result: Optional[bool]
    active_enter_timestamp_monotonic: float
    inactive_exit_timestamp_monotonic: float
    exec_main_start_timestamp_monotonic: Optional[float]
    exec_main_exit_timestamp_monotonic: Optional[float]

    def is_valid(self) -> bool:
        return bool(
            self.inactive_exit_timestamp_monotonic
            or self.active_enter_timestamp_monotonic
        )

    @property
    def time_to_activate(self) -> float:
        if (
            self.active_enter_timestamp_monotonic
            and self.inactive_exit_timestamp_monotonic
        ):
            return (
                self.active_enter_timestamp_monotonic
                - self.inactive_exit_timestamp_monotonic
            )

        if (
            self.exec_main_exit_timestamp_monotonic
            and self.exec_main_start_timestamp_monotonic
        ):
            return (
                self.exec_main_exit_timestamp_monotonic
                - self.exec_main_start_timestamp_monotonic
            )

        raise ValueError("never activated")

    @classmethod
    def query(cls, service_name: str) -> "Service":
        exec_main_start_timestamp_monotonic: Optional[float] = None
        exec_main_exit_timestamp_monotonic: Optional[float] = None

        properties = query_systemctl_show(service_name)

        after = frozenset(properties.get("After", "").split())
        active_enter_timestamp_monotonic = convert_systemctl_monotonic(
            properties["ActiveEnterTimestampMonotonic"]
        )
        inactive_exit_timestamp_monotonic = convert_systemctl_monotonic(
            properties["InactiveExitTimestampMonotonic"]
        )

        timestamp = properties.get("ExecMainStartTimestampMonotonic")
        if timestamp:
            exec_main_start_timestamp_monotonic = convert_systemctl_monotonic(timestamp)

        timestamp = properties.get("ExecMainExitTimestampMonotonic")
        if timestamp:
            exec_main_exit_timestamp_monotonic = convert_systemctl_monotonic(timestamp)

        condition_result = convert_systemctl_bool(properties["ConditionResult"])

        return cls(
            name=service_name,
            after=after,
            active_enter_timestamp_monotonic=active_enter_timestamp_monotonic,
            inactive_exit_timestamp_monotonic=inactive_exit_timestamp_monotonic,
            exec_main_start_timestamp_monotonic=exec_main_start_timestamp_monotonic,
            exec_main_exit_timestamp_monotonic=exec_main_exit_timestamp_monotonic,
            condition_result=condition_result,
        )


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

        service_start = (
            service.active_enter_timestamp_monotonic
            - systemd.userspace_timestamp_monotonic
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
