import dataclasses
import logging

logger = logging.getLogger("lpt.systemd")


@dataclasses.dataclass(frozen=True, eq=True)
class Service:
    name: str
    time_to_activate: float
    timestamp_monotonic_starting: float
    timestamp_monotonic_started: float

    def get_label(self, userspace_timestamp_monotonic: float) -> str:
        """Label service using times relative to start of systemd."""
        label = f"{self.name} ("
        if self.time_to_activate:
            label += f"+{self.time_to_activate:.03f}s "

        started = self.timestamp_monotonic_started - userspace_timestamp_monotonic
        label += f"@{started:.03f}s)"
        return label

    def as_dict(self) -> dict:
        return self.__dict__.copy()
