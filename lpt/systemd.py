import dataclasses
import datetime
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, FrozenSet, Optional

from .ssh import SSH

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


@dataclasses.dataclass(frozen=True, eq=True)
class SystemdUnitList:
    unit: str
    active: str
    load: str
    sub: str
    description: str

    def is_failed(self) -> bool:
        return self.active == "failed"

    def is_active(self) -> bool:
        return self.active != "inactive"

    @classmethod
    def parse_list(cls, list_properties: dict) -> "SystemdUnitList":
        unit = list_properties["unit"]
        active = list_properties["active"]
        load = list_properties["load"]
        sub = list_properties["sub"]
        description = list_properties["description"]

        return cls(
            unit=unit, active=active, load=load, sub=sub, description=description
        )


@dataclasses.dataclass(frozen=True, eq=True)
class SystemdUnitShow:
    after: FrozenSet[str]
    condition_result: Optional[bool]
    exec_main_start_timestamp_monotonic: Optional[float]
    exec_main_exit_timestamp_monotonic: Optional[float]
    active_enter_timestamp_monotonic: float
    inactive_enter_timestamp_monotonic: float
    inactive_exit_timestamp_monotonic: float

    def get_time_to_activate(self) -> float:
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

        if (
            self.inactive_exit_timestamp_monotonic
            and self.inactive_enter_timestamp_monotonic
        ):
            # Service may have failed to start.
            return (
                self.inactive_exit_timestamp_monotonic
                - self.inactive_enter_timestamp_monotonic
            )

        raise ValueError(f"unable to determine time to activate: {self}")

    def get_time_of_activation(self) -> float:
        if self.active_enter_timestamp_monotonic:
            return self.active_enter_timestamp_monotonic

        if self.exec_main_exit_timestamp_monotonic:
            return self.exec_main_exit_timestamp_monotonic

        if self.inactive_exit_timestamp_monotonic:
            # Service may have failed to start.
            return self.inactive_exit_timestamp_monotonic

        raise ValueError(f"unable to determine time of completion: {self}")

    @classmethod
    def parse_show(cls, show_properties: dict) -> "SystemdUnitShow":
        exec_main_start_timestamp_monotonic: Optional[float] = None
        exec_main_exit_timestamp_monotonic: Optional[float] = None

        after = frozenset(show_properties.get("After", "").split())
        active_enter_timestamp_monotonic = convert_systemctl_monotonic(
            show_properties["ActiveEnterTimestampMonotonic"]
        )
        inactive_exit_timestamp_monotonic = convert_systemctl_monotonic(
            show_properties["InactiveExitTimestampMonotonic"]
        )
        inactive_enter_timestamp_monotonic = convert_systemctl_monotonic(
            show_properties["InactiveEnterTimestampMonotonic"]
        )

        timestamp = show_properties.get("ExecMainStartTimestampMonotonic")
        if timestamp:
            exec_main_start_timestamp_monotonic = convert_systemctl_monotonic(timestamp)

        timestamp = show_properties.get("ExecMainExitTimestampMonotonic")
        if timestamp:
            exec_main_exit_timestamp_monotonic = convert_systemctl_monotonic(timestamp)

        condition_result = convert_systemctl_bool(show_properties["ConditionResult"])

        return cls(
            after=after,
            condition_result=condition_result,
            exec_main_start_timestamp_monotonic=exec_main_start_timestamp_monotonic,
            exec_main_exit_timestamp_monotonic=exec_main_exit_timestamp_monotonic,
            active_enter_timestamp_monotonic=active_enter_timestamp_monotonic,
            inactive_enter_timestamp_monotonic=inactive_enter_timestamp_monotonic,
            inactive_exit_timestamp_monotonic=inactive_exit_timestamp_monotonic,
        )


@dataclasses.dataclass(frozen=True, eq=True)
class SystemdUnit(SystemdUnitShow, SystemdUnitList):
    @classmethod
    def parse(  # pylint: disable=too-many-locals
        cls, *, list_properties: dict, show_properties: dict
    ) -> "SystemdUnit":
        unit_list = SystemdUnitList.parse_list(list_properties)
        unit_show = SystemdUnitShow.parse_show(show_properties)

        return cls(**unit_list.__dict__, **unit_show.__dict__)


class Systemctl:
    @classmethod
    def show(
        cls,
        service_name: Optional[str] = None,
        *,
        output_dir: Path,
        run=subprocess.run,
    ) -> Dict[str, str]:
        properties = {}

        cmd = ["systemctl", "show"]
        if service_name:
            cmd.extend(["--", service_name])
        try:
            logger.debug("Executing: %r", cmd)
            proc = run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            logger.error("cmd (%r) failed (error=%r)", cmd, error)
            raise

        # Save captured data
        if service_name:
            log = output_dir / f"systemctl-show-{service_name}.json"
        else:
            log = output_dir / "systemctl-show.json"
        log.write_text(proc.stdout)

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

    @classmethod
    def load_units_remote(cls, ssh: SSH, *, output_dir: Path) -> Dict[str, SystemdUnit]:
        return cls.load_units(run=ssh.run, output_dir=output_dir)  # type: ignore

    @classmethod
    def load_units(
        cls, *, output_dir: Path, run=subprocess.run
    ) -> Dict[str, SystemdUnit]:
        units = {}

        cmd = ["systemctl", "list-units", "--all", "-o", "json"]
        try:
            logger.debug("Executing: %r", cmd)
            proc = run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            logger.error("cmd (%r) failed (error=%r)", cmd, error)
            raise

        # Save captured data
        log = output_dir / "systemctl-list-units.json"
        log.write_text(proc.stdout)

        output = json.loads(proc.stdout)
        for list_properties in output:
            name = list_properties["unit"]
            show_properties = cls.show(name, output_dir=output_dir, run=run)
            unit = SystemdUnit.parse(
                list_properties=list_properties, show_properties=show_properties
            )
            units[name] = unit

        return units


@dataclasses.dataclass(frozen=True, eq=True)
class Systemd:
    userspace_timestamp: datetime.datetime
    userspace_timestamp_monotonic: float
    finish_timestamp: datetime.datetime
    finish_timestamp_monotonic: float

    @classmethod
    def load_remote(cls, ssh: SSH, *, output_dir: Path) -> "Systemd":
        properties = Systemctl.show(output_dir=output_dir, run=ssh.run)  # type: ignore
        return cls.parse(properties)

    @classmethod
    def load(cls, *, output_dir: Path) -> "Systemd":
        properties = Systemctl.show(output_dir=output_dir)
        return cls.parse(properties)

    @classmethod
    def parse(cls, properties: dict) -> "Systemd":
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
