import dataclasses
import datetime
import logging
import re
from collections import deque
from pathlib import Path
from typing import List, Optional, Union

import dateutil.parser

from .event import Event
from .time import calculate_reference_timestamp

logger = logging.getLogger("lpt.cloudinit")


@dataclasses.dataclass
class CloudInitFrame(Event):
    stage: str
    module: str
    timestamp_realtime_finish: datetime.datetime
    timestamp_realtime_start: datetime.datetime
    timestamp_monotonic_finish: float
    timestamp_monotonic_start: float
    duration: float
    result: str

    def as_dict(self) -> dict:
        obj = self.__dict__.copy()
        obj["timestamp_realtime"] = str(self.timestamp_realtime)
        obj["timestamp_realtime_start"] = str(self.timestamp_realtime)
        obj["timestamp_realtime_finish"] = str(self.timestamp_realtime)
        return obj


@dataclasses.dataclass
class CloudInitEvent(Event):
    log_line: str
    log_level: str
    message: str
    module: str
    result: Optional[str]
    timestamp_realtime: datetime.datetime
    timestamp_monotonic: float
    event_type: str
    stage: Optional[str]


@dataclasses.dataclass
class CloudInitEntry:
    log_line: str
    log_level: str
    message: str
    module: str
    result: Optional[str]
    timestamp_realtime: datetime.datetime
    timestamp_monotonic: float
    event_type: str
    stage: Optional[str]

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
        if message.startswith("finish:"):
            split = message.split(": ")
            event_type = split[0]
            stage = split[1]
            result = split[2]
            message = ": ".join(split[3:])

        # Start event
        if message.startswith("start:"):
            split = message.split(": ")
            event_type = split[0]
            stage = split[1]
            message = ": ".join(split[2:])

        entry = cls(
            log_line=log_line,
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

    def as_event(self, label: str) -> CloudInitEvent:
        return CloudInitEvent(**self.__dict__, label=label, source="cloudinit")


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
        last_timestamp = None

        logs = path.read_text(encoding="utf-8")
        for line in logs.splitlines():
            try:
                entry = CloudInitEntry.parse(line, reference_monotonic)
            except ValueError:
                continue
            finally:
                boot_logs.append(line)

            # Due to low resolution, add a microsecond to timestamp if it
            # matches the previous record.
            if (
                last_timestamp is not None
                and entry.timestamp_realtime <= last_timestamp
            ):
                entry.timestamp_realtime = last_timestamp + datetime.timedelta(
                    microseconds=1
                )
            last_timestamp = entry.timestamp_realtime

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

    def get_frames(self) -> List[CloudInitFrame]:
        stack: deque[CloudInitEntry] = deque()
        frames: List[CloudInitFrame] = []
        for entry in self.entries:
            if entry.event_type == "start":
                print("start of frame:", entry)
                stack.append(entry)
            if entry.event_type == "finish":
                assert stack
                start = stack.pop()
                print("finish of frame:", entry, start)
                assert start.event_type == "start"
                assert start.stage == entry.stage
                assert entry.result
                assert entry.stage
                frame = CloudInitFrame(
                    source="cloudinit",
                    label="CLOUDINIT_FRAME",
                    timestamp_realtime=start.timestamp_realtime,
                    timestamp_monotonic=start.timestamp_monotonic,
                    duration=entry.timestamp_monotonic - start.timestamp_monotonic,
                    stage=entry.stage,
                    module=entry.module,
                    timestamp_realtime_finish=entry.timestamp_realtime,
                    timestamp_monotonic_finish=entry.timestamp_monotonic,
                    timestamp_realtime_start=start.timestamp_realtime,
                    timestamp_monotonic_start=start.timestamp_monotonic,
                    result=entry.result,
                )
                frames.append(frame)
                print("frame: ", frame)
        return frames

    def get_events_of_interest(  # pylint:disable=too-many-branches
        self,
    ) -> List[Union[CloudInitEvent, CloudInitFrame]]:
        events: List[Union[CloudInitEvent, CloudInitFrame]] = []

        events.extend(self.get_frames())

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

        for entry in self.find_entries("PPS type:"):
            events.append(entry.as_event("CLOUDINIT_PPS_TYPE"))

        for entry in self.find_entries("PreprovisionedVMType:"):
            events.append(entry.as_event("CLOUDINIT_PPS_TYPE"))

        for entry in self.find_entries("", event_type="start"):
            events.append(entry.as_event("CLOUDINIT_FRAME_START"))

        for entry in self.find_entries("", event_type="finish"):
            events.append(entry.as_event("CLOUDINIT_FRAME_FINISH"))

        for entry in self.find_entries("ERROR"):
            events.append(entry.as_event("ERROR_CLOUDINIT_ERROR"))

        for entry in self.find_entries("WARNING"):
            events.append(entry.as_event("ERROR_CLOUDINIT_WARNING"))

        for entry in self.find_entries("CRITICAL"):
            events.append(entry.as_event("ERROR_CLOUDINIT_CRITICAL"))

        for entry in self.find_entries("Traceback"):
            events.append(entry.as_event("ERROR_CLOUDINIT_TRACEBACK"))

        failed_entries = [e for e in self.entries if e.result not in (None, "SUCCESS")]
        for entry in failed_entries:
            if entry.message == "load_azure_ds_dir":
                continue
            events.append(entry.as_event(f"ERROR_UNEXPECTED_FAILURE {entry.result}"))

        for entry in self.find_entries("FAIL"):
            if "load_azure_ds_dir" in entry.message:
                continue
            events.append(entry.as_event("ERROR_CLOUDINIT_FAIL"))

        for entry in self.find_entries("_get_data", event_type="start")[1:]:
            events.append(entry.as_event("WARNING_CLOUDINIT_UNEXPECTED_GET_DATA"))

        return events
