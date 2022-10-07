import dataclasses
import datetime
import logging

logger = logging.getLogger("lpt.event")


@dataclasses.dataclass
class Event:
    label: str
    timestamp_realtime: datetime.datetime
    timestamp_monotonic: float
    source: str

    def estimate_timestamp_monotonic(
        self, reference_monotonic: datetime.datetime
    ) -> None:
        self.timestamp_monotonic = (
            self.timestamp_realtime - reference_monotonic
        ).total_seconds()

    def as_dict(self) -> dict:
        obj = self.__dict__.copy()
        obj["timestamp_realtime"] = str(self.timestamp_realtime)
        return obj
