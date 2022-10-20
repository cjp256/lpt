import dataclasses
import datetime
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Optional

import dateutil.parser

from .event import Event
from .ssh import SSH

logger = logging.getLogger("lpt.journal")


@dataclasses.dataclass
class JournalEvent(Event):
    message: str


@dataclasses.dataclass
class JournalEntry:
    message: str
    timestamp_realtime: datetime.datetime
    timestamp_monotonic: float

    @classmethod
    def parse(cls, entry: dict) -> "JournalEntry":
        timestamp_realtime = None
        for ts_type in ["_SOURCE_REALTIME_TIMESTAMP", "__REALTIME_TIMESTAMP"]:
            ts = entry.get(ts_type)
            if ts is None:
                continue
            timestamp_realtime = cls.convert_realtime_timestamp_to_datetime(int(ts))
            break

        timestamp_monotonic = None
        for ts_type in ["_SOURCE_MONOTONIC_TIMESTAMP", "__MONOTONIC_TIMESTAMP"]:
            ts = entry.get(ts_type)
            if ts is None:
                continue
            timestamp_monotonic = float(ts) / 1000 / 1000
            break

        message = entry["MESSAGE"]

        assert timestamp_monotonic is not None, f"no monotonic timestamp? {entry}"
        assert timestamp_realtime is not None, f"no realtime timestamp? {entry}"

        return cls(
            message=message,
            timestamp_realtime=timestamp_realtime,
            timestamp_monotonic=timestamp_monotonic,
        )

    @staticmethod
    def convert_realtime_timestamp_to_datetime(microseconds: int) -> datetime.datetime:
        return datetime.datetime.utcfromtimestamp(0) + datetime.timedelta(
            microseconds=microseconds
        )

    @staticmethod
    def parse_line_timestamp_monotonic(log_line: str) -> float:
        return float(re.findall(r"\[[0-9]+\.[0-9]+\]", log_line)[0][1:-1])

    @staticmethod
    def parse_line_timestamp_iso(log_line: str) -> datetime.datetime:
        ts = log_line.split(" ")[0]
        try:
            return dateutil.parser.isoparse(ts)
        except ValueError as error:
            logger.error("Failed to parse ts=%r (%r)", ts, error)
            raise

    def as_event(self, label: str) -> JournalEvent:
        return JournalEvent(**self.__dict__.copy(), label=label, source="journal")


@dataclasses.dataclass
class Journal:
    entries: List[JournalEntry]

    @classmethod
    def load_remote(cls, ssh: SSH, *, output_dir: Path) -> List["Journal"]:
        cmd = ["journalctl", "-o", "json"]

        journal_log = output_dir / "journal.log"
        stdout, _, _ = ssh.run(cmd, capture_output=True, check=True)
        assert isinstance(stdout, bytes)
        journal_log.write_bytes(stdout)
        return cls.parse_json(stdout)

    @classmethod
    def load(cls, *, output_dir: Path, journal_path: Optional[Path]) -> List["Journal"]:
        cmd = ["journalctl", "-o", "json"]
        if journal_path:
            cmd.extend(["-D", journal_path.as_posix()])

        journal_log = output_dir / "journal.log"
        proc = subprocess.run(cmd, capture_output=True, check=True)
        journal_log.write_bytes(proc.stdout)
        return cls.parse_json(proc.stdout)

    @classmethod
    def parse_json(cls, logs: bytes) -> List["Journal"]:
        """Parse journal and split by boot."""
        boot_entries: List[JournalEntry] = []
        journals = []

        entries = [JournalEntry.parse(json.loads(log)) for log in logs.splitlines()]
        for entry in entries:
            if entry.message.startswith("Linux version") and boot_entries:
                boot_journal = cls(entries=boot_entries)
                journals.append(boot_journal)
                boot_entries = [entry]
            else:
                boot_entries.append(entry)

        if boot_entries:
            boot_journal = cls(entries=boot_entries)
            journals.append(boot_journal)

        return journals

    def find_entries(self, pattern) -> List[JournalEntry]:
        return [e for e in self.entries if re.search(pattern, e.message)]

    def get_events_of_interest(  # pylint:disable=too-many-branches
        self,
    ) -> List[JournalEvent]:
        events = []

        for entry in self.find_entries("Linux version"):
            events.append(entry.as_event("KERNEL_BOOT"))
            break

        for entry in self.find_entries(".*link becomes ready"):
            events.append(entry.as_event("LINK_READY"))

        for stage in ["DISCOVER", "OFFER", "REQUEST", "ACK"]:
            for entry in self.find_entries(f"DHCP{stage}"):
                events.append(entry.as_event(f"EPHEMERAL_DHCP_{stage}"))

        for entry in self.find_entries("systemd .* running in system mode.*"):
            events.append(entry.as_event("SYSTEMD_STARTED"))

        for entry in self.find_entries("Server listening on 0.0.0.0 port 22"):
            events.append(entry.as_event("SSH_LISTENING"))

        for entry in self.find_entries("Accepted publickey"):
            events.append(entry.as_event("SSH_ACCEPTED_CONNECTION"))
            break

        for entry in self.find_entries("Startup finished in.*(firmware).*"):
            events.append(entry.as_event("STARTUP_FINISHED"))
            break

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

        for entry in self.find_entries(
            "Your identification has been saved in /etc/ssh/ssh_host_ecdsa_key"
        ):
            events.append(entry.as_event("SSH_HOST_KEYS_GENERATED"))

        for entry in self.find_entries(r"^new group:"):
            events.append(entry.as_event("CREATED_GROUP"))

        for entry in self.find_entries(r"^new user:"):
            events.append(entry.as_event("CREATED_USER"))

        for entry in self.find_entries(r"^Starting"):
            events.append(entry.as_event("SERVICE_STARTING"))

        for entry in self.find_entries(r"^Started"):
            events.append(entry.as_event("SERVICE_STARTED"))

        for entry in self.find_entries(r"^Reached target"):
            events.append(entry.as_event("TARGET_REACHED"))

        for entry in self.find_entries("System clock wrong"):
            events.append(entry.as_event("WARNING_CHRONY_SYSTEM_CLOCK_WRONG"))

        for entry in self.find_entries("System clock was stepped"):
            events.append(entry.as_event("WARNING_CHRONY_SYSTEM_CLOCK_STEPPED"))

        for entry in self.find_entries("segfault"):
            events.append(entry.as_event("ERROR_SEGFAULT"))

        return events
