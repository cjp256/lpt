import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List

from .cloudinit import CloudInit
from .event import Event
from .journal import Journal

logger = logging.getLogger("lpt")


def _init_logger(log_level: int):
    logger.setLevel(log_level)
    formatter = logging.Formatter(
        "%(created)f:%(levelname)s:%(name)s:%(module)s:%(message)s"
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(log_level)
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def analyze_journal(journal_json_path: str) -> List[Event]:
    logger.debug("Analyzing: %s", journal_json_path)
    if journal_json_path == "local":
        journals = Journal.load_journal_host()
    elif journal_json_path:
        journal_path = Path(journal_json_path)
        journals = Journal.load_journal_path(journal_path)
    else:
        return []

    events = []
    for journal in journals:
        events += journal.get_events_of_interest()

    return events


def analyze_cloudinit(cloudinit_log_path: str) -> List[Event]:
    logger.debug("Analyzing: %s", cloudinit_log_path)

    if cloudinit_log_path == "local":
        log_path = Path("/var/log/cloud-init.log")
    elif cloudinit_log_path:
        log_path = Path(cloudinit_log_path)
    else:
        return []

    cloudinits = CloudInit.parse(log_path)
    events = []
    for cloudinit in cloudinits:
        events += cloudinit.get_events_of_interest()

    return events


def analyze(args):
    if args.journal_json_path:
        events = analyze_journal(args.journal_json_path)
    else:
        events = []

    if args.cloudinit_log_path:
        events += analyze_cloudinit(args.cloudinit_log_path)

    events = sorted(events, key=lambda x: x.timestamp_realtime)
    event_dicts = [e.as_dict() for e in events]

    warnings = [e for e in event_dicts if e["label"].startswith("WARNING")]
    errors = [e for e in event_dicts if e["label"].startswith("ERROR")]

    output = {
        "events": event_dicts,
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(output, indent=4))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug", help="output debug info", action="store_true", default=True
    )

    subparsers = parser.add_subparsers()
    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument(
        "--journal-json-path",
        help="journal json logs path, use 'local' to fetch directly",
    )
    analyze_parser.add_argument(
        "--cloudinit-log-path",
        help="cloudinit logs path, use 'local' to fetch directly",
    )
    analyze_parser.set_defaults(func=analyze)

    args = parser.parse_args()

    if args.debug:
        _init_logger(logging.DEBUG)
    else:
        _init_logger(logging.INFO)

    args.func(args)


if __name__ == "__main__":
    main()
