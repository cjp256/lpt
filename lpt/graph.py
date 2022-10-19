import dataclasses
import logging
from typing import Dict, List, Optional, Set, Tuple

from .cloudinit import CloudInitFrame
from .systemd import Systemd, SystemdUnit

logger = logging.getLogger("lpt.graph")


@dataclasses.dataclass
class ServiceGraph:
    def __init__(
        self,
        service_name: str,
        *,
        filter_services: List[str],
        filter_conditional_result_no: bool = False,
        filter_inactive: bool = True,
        systemd: Optional[Systemd] = None,
        units: Optional[Dict[str, SystemdUnit]] = None,
        frames: Optional[List[CloudInitFrame]] = None,
    ) -> None:

        self.service_name = service_name
        self.filter_services = filter_services
        self.filter_conditional_result_no = filter_conditional_result_no
        self.filter_inactive = filter_inactive

        self.systemd = systemd if systemd else Systemd.query()
        self.units: Dict[str, SystemdUnit] = units if units else {}
        self.frames: List[CloudInitFrame] = frames if frames else []

    def get_frame_label(self, frame: CloudInitFrame) -> str:
        """Label cloud-init frame."""
        label = frame.module
        notes = []

        time_to_activate = frame.get_time_to_complete()
        if time_to_activate:
            notes.append(f"+{time_to_activate:.03f}s")

        time_of_activation = frame.get_time_of_completion()
        notes.append(f"@{time_of_activation:.03f}s")

        if frame.is_failed():
            notes.append("*FAILED*")

        if notes:
            label += " (" + " ".join(notes) + ")"

        return label

    def get_unit_label(self, unit: SystemdUnit) -> str:
        """Label systemd unit."""
        label = unit.unit
        notes = []

        time_to_activate = unit.get_time_to_activate()
        if time_to_activate:
            notes.append(f"+{time_to_activate:.03f}s")

        time_of_activation = unit.get_time_of_activation()
        notes.append(f"@{time_of_activation:.03f}s")

        if unit.is_failed():
            notes.append("*FAILED*")

        if notes:
            label += " (" + " ".join(notes) + ")"

        return label

    def walk_unit_dependencies(
        self,
    ) -> Set[Tuple[SystemdUnit, SystemdUnit]]:
        deps = set()
        seen = set()

        def _walk_dependencies(service_name: str) -> None:
            logger.debug("walking: %s", service_name)
            if service_name in seen:
                logger.debug("seen: %s", service_name)
                return

            seen.add(service_name)

            service = self.units.get(service_name)
            if service is None:
                return

            for name in service.after:
                dependency = self.units.get(name)
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

                deps.add((service, dependency))
                _walk_dependencies(name)

        _walk_dependencies(self.service_name)

        return deps

    def as_dict(self) -> dict:
        return self.__dict__.copy()

    def generate_digraph(
        self,
    ) -> str:
        edges = set()

        unit_dependencies = self.walk_unit_dependencies()
        graphed_units = set()

        for s1, s2 in sorted(unit_dependencies, key=lambda x: x[0].unit):
            graphed_units.add(s1)
            graphed_units.add(s2)
            label_s1 = self.get_unit_label(s1)
            label_s2 = self.get_unit_label(s2)
            color = "red" if s2.is_failed() else "green"

            edges.add(f'  "{label_s1}"->"{label_s2}" [color="{color}"];')

        # Add cloud-init frames.
        for service_name, stage in {
            "cloud-init-local.service": "init-local",
            "cloud-init.service": "init-network",
            "cloud-config.service": "modules-config",
            "cloud-final.service": "modules-final",
        }.items():

            service = self.units[service_name]
            if service not in graphed_units:
                continue

            label_s1 = self.get_unit_label(service)
            stage_frames = [f for f in self.frames if f.stage == stage]
            for frame in stage_frames:
                color = "red" if frame.is_failed() else "green"

                label_s2 = self.get_frame_label(frame)
                edges.add(f'  "{label_s1}"->"{label_s2}" [color="{color}"];')

        lines = [
            f'digraph "{self.service_name}" {{',
            "  rankdir=LR;",
            *sorted(edges),
            "}",
        ]
        return "\n".join(lines)
