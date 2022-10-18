import dataclasses
import datetime
import logging
import subprocess
from typing import Dict, FrozenSet, Optional

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

    def calculate_relative_time_of_activation(
        self, userspace_timestamp_monotonic: float
    ) -> float:
        return self.active_enter_timestamp_monotonic - userspace_timestamp_monotonic

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
