import dataclasses
import datetime
import logging
from typing import Optional

logger = logging.getLogger("lpt.event")


@dataclasses.dataclass
class Event:
    label: Optional[str]
    data: Optional[str]
    source: str
    timestamp_realtime: datetime.datetime
    timestamp_monotonic: float

    def estimate_monotonic(self, reference_event: "Event") -> None:
        time_diff = (
            self.timestamp_realtime - reference_event.timestamp_realtime
        ).total_seconds()
        self.timestamp_monotonic = reference_event.timestamp_monotonic + time_diff

    def as_dict(self) -> dict:
        obj = self.__dict__.copy()
        obj["timestamp_realtime"] = str(self.timestamp_realtime)
        return obj
