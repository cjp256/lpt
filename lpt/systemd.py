import dataclasses
import datetime
import logging
import subprocess
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from .service import Service

logger = logging.getLogger("lpt.systemd")


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
class SystemdService(Service):
    name: str
    after: FrozenSet[str]
    condition_result: Optional[bool]
    active_enter_timestamp_monotonic: float
    inactive_enter_timestamp_monotonic: float
    inactive_exit_timestamp_monotonic: float
    exec_main_start_timestamp_monotonic: Optional[float]
    exec_main_exit_timestamp_monotonic: Optional[float]

    def is_valid(self) -> bool:
        return bool(
            self.inactive_exit_timestamp_monotonic
            or self.active_enter_timestamp_monotonic
        )

    @classmethod
    def query(  # pylint: disable=too-many-locals
        cls, service_name: str, *, userspace_timestamp_monotonic: float
    ) -> "SystemdService":
        exec_main_start_timestamp_monotonic: Optional[float] = None
        exec_main_exit_timestamp_monotonic: Optional[float] = None
        time_to_activate = 0.0
        timestamp_monotonic_start = 0.0
        timestamp_monotonic_finish = 0.0
        failed = False

        properties = query_systemctl_show(service_name)

        after = frozenset(properties.get("After", "").split())
        active_enter_timestamp_monotonic = convert_systemctl_monotonic(
            properties["ActiveEnterTimestampMonotonic"]
        )
        inactive_exit_timestamp_monotonic = convert_systemctl_monotonic(
            properties["InactiveExitTimestampMonotonic"]
        )
        inactive_enter_timestamp_monotonic = convert_systemctl_monotonic(
            properties["InactiveEnterTimestampMonotonic"]
        )

        timestamp = properties.get("ExecMainStartTimestampMonotonic")
        if timestamp:
            exec_main_start_timestamp_monotonic = convert_systemctl_monotonic(timestamp)

        timestamp = properties.get("ExecMainExitTimestampMonotonic")
        if timestamp:
            exec_main_exit_timestamp_monotonic = convert_systemctl_monotonic(timestamp)

        condition_result = convert_systemctl_bool(properties["ConditionResult"])

        if active_enter_timestamp_monotonic and inactive_exit_timestamp_monotonic:
            time_to_activate = (
                active_enter_timestamp_monotonic - inactive_exit_timestamp_monotonic
            )
            timestamp_monotonic_start = (
                inactive_exit_timestamp_monotonic - userspace_timestamp_monotonic
            )
            timestamp_monotonic_finish = (
                active_enter_timestamp_monotonic - userspace_timestamp_monotonic
            )
        elif exec_main_exit_timestamp_monotonic and exec_main_start_timestamp_monotonic:
            time_to_activate = (
                exec_main_exit_timestamp_monotonic - exec_main_start_timestamp_monotonic
            )
            timestamp_monotonic_start = (
                exec_main_start_timestamp_monotonic - userspace_timestamp_monotonic
            )
            timestamp_monotonic_finish = (
                exec_main_exit_timestamp_monotonic - userspace_timestamp_monotonic
            )
        elif inactive_exit_timestamp_monotonic and inactive_enter_timestamp_monotonic:
            # Service may have failed to start.
            time_to_activate = timestamp_monotonic_finish - timestamp_monotonic_start
            timestamp_monotonic_start = (
                inactive_exit_timestamp_monotonic - userspace_timestamp_monotonic
            )
            timestamp_monotonic_finish = (
                inactive_enter_timestamp_monotonic - userspace_timestamp_monotonic
            )
            failed = True

        return cls(
            name=service_name,
            time_to_activate=time_to_activate,
            timestamp_monotonic_start=timestamp_monotonic_start,
            timestamp_monotonic_finish=timestamp_monotonic_finish,
            failed=failed,
            after=after,
            active_enter_timestamp_monotonic=active_enter_timestamp_monotonic,
            inactive_enter_timestamp_monotonic=inactive_enter_timestamp_monotonic,
            inactive_exit_timestamp_monotonic=inactive_exit_timestamp_monotonic,
            exec_main_start_timestamp_monotonic=exec_main_start_timestamp_monotonic,
            exec_main_exit_timestamp_monotonic=exec_main_exit_timestamp_monotonic,
            condition_result=condition_result,
        )


def walk_systemd_service_dependencies(
    service_name: str,
    *,
    filter_services: List[str],
    filter_conditional_result_no: bool = False,
    filter_inactive: bool = True,
) -> Set[Tuple[SystemdService, SystemdService]]:
    deps = set()
    seen = set()
    service_cache: Dict[str, SystemdService] = {}
    systemd = Systemd.query()
    userspace_timestamp_monotonic = systemd.userspace_timestamp_monotonic

    def _walk_dependencies(service_name: str) -> None:
        if service_name in seen:
            return
        seen.add(service_name)

        service = SystemdService.query(
            service_name,
            userspace_timestamp_monotonic=userspace_timestamp_monotonic,
        )
        if service is None:
            return

        service_cache[service_name] = service
        for dep_name in service.after:
            if dep_name in service_cache:
                service_dep = service_cache[dep_name]
            else:
                service_dep = SystemdService.query(
                    dep_name,
                    userspace_timestamp_monotonic=userspace_timestamp_monotonic,
                )
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
