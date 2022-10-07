import dataclasses
import datetime
import logging
import re
from pathlib import Path
from typing import List, Optional

import dateutil.parser

from .event import Event
from .time import calculate_reference_timestamp

logger = logging.getLogger("lpt.cloudinit")


@dataclasses.dataclass
class CloudInitEntry:
    data: str
    log_level: str
    message: str
    module: str
    result: Optional[str]
    timestamp_realtime: datetime.datetime
    timestamp_monotonic: float
    event_type: str
    stage: Optional[str]

    def as_event(self, label: str) -> Event:
        return Event(
            label=label,
            data=self.data,
            source="cloudinit",
            timestamp_realtime=self.timestamp_realtime,
            timestamp_monotonic=self.timestamp_monotonic,
        )

    @classmethod
    def parse(
        cls, log_line: str, reference_monotonic: Optional[datetime.datetime] = None
    ) -> "CloudInitEntry":
        line_match = re.search(r"(.*) - (.*)\[(.*)\]: (.*)", log_line)
        if line_match is None:
            raise ValueError(f"unable to parse: {log_line}")

        ts, module, log_level, message = line_match.groups()
        timestamp_realtime = cls.convert_timestamp_to_datetime(ts)

        if message.startswith("start:"):
            event_type = "start"
        elif message.startswith("finish:"):
            event_type = "finish"

        event_type = "log"
        result = None
        stage = None

        # Finish event
        line_match = re.search(r"(.*): (.*): (.*): (.*)", message)
        if line_match:
            event_type, stage, result, message = line_match.groups()

        # Start event
        line_match = re.search(r"(.*): (.*): (.*)", message)
        if line_match:
            event_type, stage, message = line_match.groups()

        entry = cls(
            data=log_line,
            event_type=event_type,
            log_level=log_level,
            message=message,
            module=module,
            result=result,
            stage=stage,
            timestamp_realtime=timestamp_realtime,
            timestamp_monotonic=0.0,
        )

        if reference_monotonic:
            entry.estimate_timestamp_monotonic(reference_monotonic)
        else:
            entry.check_for_monotonic_reference()

        return entry

    @staticmethod
    def convert_timestamp_to_datetime(timestamp: str) -> datetime.datetime:
        return dateutil.parser.isoparse(timestamp)

    def estimate_timestamp_monotonic(
        self, reference_monotonic: datetime.datetime
    ) -> None:
        self.timestamp_monotonic = (
            self.timestamp_realtime - reference_monotonic
        ).total_seconds()

    def check_for_monotonic_reference(self) -> Optional[datetime.datetime]:
        uptime_match = re.search(".* Up (.*) seconds", self.message)
        if not uptime_match:
            return None

        monotonic_time = float(uptime_match.groups()[0])
        reference_monotonic = calculate_reference_timestamp(
            self.timestamp_realtime, monotonic_time
        )
        self.estimate_timestamp_monotonic(reference_monotonic)
        return reference_monotonic

    def is_start_of_boot_record(self) -> bool:
        return bool(re.search("Cloud-init .* running 'init-local'", self.message))


@dataclasses.dataclass
class CloudInit:
    logs: str
    entries: List[CloudInitEntry]
    reference_monotonic: Optional[datetime.datetime]

    @classmethod
    def parse(cls, path: Path = Path("/var/log/cloud-init.log")) -> List["CloudInit"]:
        """Parse cloud-init log and split by boot."""
        cloudinits = []
        boot_entries: List[CloudInitEntry] = []
        boot_logs: List[str] = []
        reference_monotonic = None

        logs = path.read_text(encoding="utf-8")
        for line in logs.splitlines():
            try:
                entry = CloudInitEntry.parse(line, reference_monotonic)
            except ValueError:
                continue
            finally:
                boot_logs.append(line)

            timestamp = entry.check_for_monotonic_reference()
            if timestamp is not None:
                reference_monotonic = timestamp

            if entry.is_start_of_boot_record() and boot_entries:
                # New boot, ensure all entries have estimated monotonic.
                for entry in boot_entries:
                    if entry.timestamp_monotonic == 0.0 and reference_monotonic:
                        entry.estimate_timestamp_monotonic(reference_monotonic)

                boot_cloudinit = CloudInit(
                    entries=boot_entries,
                    reference_monotonic=reference_monotonic,
                    logs="\n".join(boot_logs),
                )
                cloudinits.append(boot_cloudinit)
                boot_entries = [entry]
                boot_logs = []
            else:
                boot_entries.append(entry)

        if boot_entries:
            boot_cloudinit = CloudInit(
                entries=boot_entries,
                reference_monotonic=reference_monotonic,
                logs="\n".join(boot_logs),
            )
            cloudinits.append(boot_cloudinit)
        return cloudinits

    def find_entries(
        self, pattern, *, event_type: Optional[str] = None
    ) -> List[CloudInitEntry]:
        return [
            e
            for e in self.entries
            if re.search(pattern, e.message)
            and (event_type is None or event_type == e.event_type)
        ]

    def get_events_of_interest(self) -> List[Event]:
        events = []

        for entry in self.find_entries("running 'init-local'"):
            events.append(entry.as_event("CLOUDINIT_RUNNING_INIT_LOCAL"))

        for entry in self.find_entries("running 'init'"):
            events.append(entry.as_event("CLOUDINIT_RUNNING_INIT"))

        for entry in self.find_entries("running 'modules:config'"):
            events.append(entry.as_event("CLOUDINIT_RUNNING_MODULES_CONFIG"))

        for entry in self.find_entries("running 'modules:final'"):
            events.append(entry.as_event("CLOUDINIT_RUNNING_MODULES_FINAL"))

        for entry in self.find_entries("finished at"):
            events.append(entry.as_event("CLOUDINIT_FINISHED"))

        for entry in self.find_entries("ERROR"):
            events.append(entry.as_event("ERROR_CLOUDINIT_ERROR"))

        for entry in self.find_entries("WARNING"):
            events.append(entry.as_event("ERROR_CLOUDINIT_WARNING"))

        for entry in self.find_entries("CRITICAL"):
            events.append(entry.as_event("ERROR_CLOUDINIT_CRITICAL"))

        for entry in self.find_entries("Traceback"):
            events.append(entry.as_event("ERROR_CLOUDINIT_TRACEBACK"))

        for entry in self.find_entries("FAIL"):
            if "load_azure_ds_dir" in entry.message:
                continue
            events.append(entry.as_event("ERROR_CLOUDINIT_FAIL"))

        for entry in self.find_entries("_get_data", event_type="start")[1:]:
            events.append(entry.as_event("WARNING_CLOUDINIT_UNEXPECTED_GET_DATA"))

        return events
