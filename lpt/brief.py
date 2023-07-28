import dataclasses
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from .cloudinit import CloudInitFrame
from .systemd import Systemd, SystemdUnit

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class Unit:
    name: str
    duration: Optional[float]
    finished: float
    dependencies: List[str]
    notes: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_systemd_unit(cls, unit: SystemdUnit) -> "Unit":
        """Convert systemd unit."""
        name = unit.unit
        notes = []

        duration = unit.get_time_to_activate()
        if not duration:
            duration = 0
        duration = round(duration, 4)

        finished = unit.get_time_of_activation()
        finished = round(finished, 4)

        if unit.is_failed():
            notes.append("FAILED")

        return cls(
            name=name,
            duration=duration,
            finished=finished,
            dependencies=[],
            notes=notes,
        )

    @classmethod
    def from_cloudinit_frame(cls, frame: CloudInitFrame) -> "Unit":
        """Convert cloud-init frame."""
        name = frame.name
        notes = []

        duration = frame.get_time_to_complete()
        if not duration:
            duration = 0
        duration = round(duration, 4)

        finished = frame.get_time_of_completion()
        finished = round(finished, 4)

        if frame.is_failed():
            notes.append("FAILED")

        dependencies = [f.name for f in frame.children]
        return cls(
            name=name,
            duration=duration,
            finished=finished,
            dependencies=dependencies,
            notes=notes,
        )


class ServiceBrief:
    def __init__(
        self,
        *,
        systemd: Systemd,
        filter_services: List[str],
        filter_conditional_result_no: bool = False,
        filter_inactive: bool = True,
        frames: Optional[List[CloudInitFrame]] = None,
        service_name: str = "multi-user.target",
    ) -> None:
        self.service_name = service_name
        self.filter_services = filter_services
        self.filter_conditional_result_no = filter_conditional_result_no
        self.filter_inactive = filter_inactive

        self.systemd = systemd
        self.frames: List[CloudInitFrame] = frames if frames else []
        self.units: Dict[str, Unit] = {}
        self.populate_units()

    def walk_frame_dependencies(
        self
    ) -> Set[Tuple[CloudInitFrame, CloudInitFrame]]:
        roots = [f for f in self.frames if f.parent is None and f.service in self.units.keys()]

        deps = set()
        seen = set()

        def _walk_dependencies(frame: CloudInitFrame) -> None:
            # logger.debug("walking: %s", frame)
            if frame in seen:
                # logger.debug("seen: %s", frame)
                return

            seen.add(frame)

            conflicting_unit = self.units.get(frame.name)
            if conflicting_unit is not None:
                for i in range(0, 100):
                    name =
                    if 
                return
            unit = Unit.from_cloudinit_frame(frame)
            self.units[frame.name] = unit

            for child in frame.children:
                deps.add((frame, child))
                _walk_dependencies(child)

        for root in roots:
            _walk_dependencies(root)

        return deps

    def walk_unit_dependencies(
        self,
    ) -> Set[Tuple[SystemdUnit, SystemdUnit]]:
        deps = set()
        seen = set()

        def _walk_dependencies(service_name: str) -> None:
            # logger.debug("walking: %s", service_name)
            if service_name in seen:
                # logger.debug("seen: %s", service_name)
                return

            seen.add(service_name)

            service = self.systemd.units.get(service_name)
            if service is None:
                logger.debug("service not found: %r", self.systemd.units)
                return

            unit_deps = set()
            for name in service.after:
                dependency = self.systemd.units.get(name)
                if dependency is None:
                    continue

                if not dependency.is_active():
                    continue

                if name in self.filter_services:
                    continue

                if (
                    self.filter_conditional_result_no
                    and not dependency.condition_result
                ):
                    continue

                if (
                    self.filter_inactive
                    and not dependency.active_enter_timestamp_monotonic
                ):
                    continue

                unit_deps.add(name)
                deps.add((service, dependency))
                _walk_dependencies(name)

            unit = Unit.from_systemd_unit(service)
            unit.dependencies = sorted(unit_deps)
            self.units[service_name] = unit

        _walk_dependencies(self.service_name)
        return deps

    def populate_units(
        self,
    ) -> None:
        self.walk_unit_dependencies()
        self.walk_frame_dependencies()

        # Add cloud-init frames.
        for service_name, stage in {
            "cloud-init-local.service": "init-local",
            "cloud-init.service": "init-network",
            "cloud-config.service": "modules-config",
            "cloud-final.service": "modules-final",
        }.items():
            service = self.units.get(service_name)
            if service is None:
                continue

            stage_root_frames = [
                f for f in self.frames if f.stage == stage and f.parent is None
            ]
            names = [f.name for f in stage_root_frames]
            service.dependencies.extend(names)

        for _, unit in self.units.items():
            unit.dependencies = sorted(set(unit.dependencies))
