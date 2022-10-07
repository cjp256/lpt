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


def print_analysis(events: List[Event]) -> None:
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


def analyze_cloudinit(
    log_path: Path = Path("/var/log/cloud-init.log"),
) -> List[CloudInit]:
    logger.debug("Analyzing cloud-init logs: %s", log_path)
    return CloudInit.parse(log_path)


def analyze_journal(journal_path: Path = Path("/var/log/journal")) -> List[Journal]:
    logger.debug("Analyzing journal logs: %s", journal_path)
    return Journal.load_journal_path(journal_path)


def main_analyze(args) -> None:
    events: List[Event] = []

    cloudinits = analyze_cloudinit(args.cloudinit_log_path)
    if args.boot:
        cloudinits = cloudinits[-1:]

    for cloudinit in cloudinits:
        events += cloudinit.get_events_of_interest()

    journals = analyze_journal(args.journal_path)
    if args.boot:
        journals = journals[-1:]

    for journal in journals:
        events += journal.get_events_of_interest()

    print_analysis(events)


def main_analyze_cloudinit(args) -> None:
    events: List[Event] = []

    cloudinits = analyze_cloudinit(args.cloudinit_log_path)
    if args.boot:
        cloudinits = cloudinits[-1:]

    for cloudinit in cloudinits:
        events += cloudinit.get_events_of_interest()

    print_analysis(events)


def main_analyze_journal(args) -> None:
    events: List[Event] = []

    journals = analyze_journal(args.journal_path)
    if args.boot:
        journals = journals[-1:]

    for journal in journals:
        events += journal.get_events_of_interest()

    print_analysis(events)


def main_help(parser, _):
    parser.print_help()


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--debug", help="output debug info", action="store_true", default=True
    )
    parser.set_defaults(func=lambda x: main_help(parser, x))

    subparsers = parser.add_subparsers()
    analyze_parser = subparsers.add_parser("analyze-cloudinit")
    analyze_parser.add_argument(
        "--boot", help="only analyze this last boot", action="store_true"
    )
    analyze_parser.add_argument(
        "--cloudinit-log-path",
        default="/var/log/cloud-init.log",
        help="cloudinit logs path, use 'local' to fetch directly",
        type=Path,
    )
    analyze_parser.set_defaults(func=main_analyze_cloudinit)

    analyze_parser = subparsers.add_parser("analyze-journal")
    analyze_parser.add_argument(
        "--boot", help="only analyze this last boot", action="store_true"
    )
    analyze_parser.add_argument(
        "--journal-path",
        default="/var/log/journal",
        help="journal directory",
        type=Path,
    )
    analyze_parser.set_defaults(func=main_analyze_journal)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument(
        "--boot", help="only analyze this last boot", action="store_true"
    )
    analyze_parser.add_argument(
        "--cloudinit-log-path",
        default="/var/log/cloud-init.log",
        help="cloudinit logs path, use 'local' to fetch directly",
        type=Path,
    )
    analyze_parser.add_argument(
        "--journal-path",
        default="/var/log/journal",
        help="journal directory",
        type=Path,
    )
    analyze_parser.set_defaults(func=main_analyze)

    args = parser.parse_args()

    if args.debug:
        _init_logger(logging.DEBUG)
    else:
        _init_logger(logging.INFO)

    args.func(args)


if __name__ == "__main__":
    main()
