import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

from .cloudinit import CloudInit
from .event import Event
from .graph import ServiceGraph
from .journal import Journal
from .ssh import SSH
from .systemd import Systemctl, Systemd

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


def print_analysis(events: List[Event], event_types: List[str]) -> None:
    events = sorted(events, key=lambda x: x.timestamp_realtime)
    if event_types:
        events = [e for e in events if e.label in event_types]

    event_dicts = [e.as_dict() for e in events]
    warnings = [e for e in event_dicts if e["label"].startswith("WARNING")]
    errors = [e for e in event_dicts if e["label"].startswith("ERROR")]

    output = {
        "events": event_dicts,
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(output, indent=4))


def load_cloudinit(args, ssh: Optional[SSH]) -> List[CloudInit]:
    if ssh:
        return CloudInit.load_remote(ssh, output_dir=args.output)

    return CloudInit.load(args.cloudinit_log_path, output_dir=args.output)


def load_journal(args, ssh: Optional[SSH]) -> List[Journal]:
    if ssh:
        return Journal.load_remote(ssh, output_dir=args.output)

    return Journal.load(journal_path=args.journal_path, output_dir=args.output)


def analyze_events(
    args, journals: List[Journal], cloudinits: List[CloudInit]
) -> List[Event]:
    events: List[Event] = []

    if args.boot:
        cloudinits = cloudinits[-1:]
        journals = journals[-1:]

    for journal in journals:
        events.extend(journal.get_events_of_interest())

    for cloudinit in cloudinits:
        events.extend(cloudinit.get_events_of_interest())

    print_analysis(events, args.event_type)
    return events


def main_analyze(args, ssh: Optional[SSH]) -> None:
    cloudinits = load_cloudinit(args, ssh)
    journals = load_journal(args, ssh)
    analyze_events(args, journals, cloudinits)


def main_analyze_cloudinit(args, ssh: Optional[SSH]) -> None:
    cloudinits = load_cloudinit(args, ssh)
    analyze_events(args, [], cloudinits)


def main_analyze_journal(args, ssh: Optional[SSH]) -> None:
    journals = load_journal(args, ssh)
    analyze_events(args, journals, [])


def main_graph(args, ssh: Optional[SSH]) -> None:
    cloudinits = load_cloudinit(args, ssh)
    if cloudinits:
        cloudinit = cloudinits[-1]
        frames = cloudinit.get_frames()
    else:
        frames = []

    systemd = Systemd.query()
    units = Systemctl.get_units()
    digraph = ServiceGraph(
        args.service,
        filter_services=sorted(args.filter_service),
        filter_conditional_result_no=args.filter_conditional_result_no,
        systemd=systemd,
        units=units,
        frames=frames,
    ).generate_digraph()

    print(digraph)


def main_help(parser, _):
    parser.print_help()


def configure_ssh(args) -> Optional[SSH]:
    if not args.ssh_host:
        return None

    ssh = SSH(
        host=args.ssh_host,
        user=args.ssh_user,
        proxy_host=args.ssh_proxy_host,
        proxy_user=args.ssh_proxy_user,
    )
    ssh.connect()

    return ssh


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--debug", help="output debug info", action="store_true")
    parser.add_argument(
        "--boot", help="only analyze this last boot", action="store_true"
    )
    parser.add_argument(
        "--journal-path",
        default="/var/log/journal",
        help="journal directory",
        type=Path,
    )
    parser.add_argument(
        "--cloudinit-log-path",
        default="/var/log/cloud-init.log",
        help="cloudinit logs path, use 'local' to fetch directly",
        type=Path,
    )
    parser.add_argument(
        "--ssh-host",
        help="collect data via ssh",
    )
    parser.add_argument(
        "--ssh-user",
        help="collect data via ssh",
    )
    parser.add_argument(
        "--ssh-proxy-host",
        help="use ssh proxy as jump host",
    )
    parser.add_argument(
        "--ssh-proxy-user",
        help="use ssh proxy as jump host",
    )
    parser.add_argument(
        "--output",
        default=Path("lpt-output"),
        help="output directory to store artifacts",
        type=Path,
    )
    parser.set_defaults(func=lambda x: main_help(parser, x))

    subparsers = parser.add_subparsers()
    analyze_parser = subparsers.add_parser("analyze-cloudinit")
    analyze_parser.set_defaults(func=main_analyze_cloudinit)

    analyze_parser = subparsers.add_parser("analyze-journal")
    analyze_parser.add_argument(
        "--event-type",
        default=[],
        help="event types to output",
        action="extend",
        nargs="+",
    )
    analyze_parser.set_defaults(func=main_analyze_journal)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument(
        "--event-type",
        default=[],
        help="event types to output",
        action="extend",
        nargs="+",
    )
    analyze_parser.set_defaults(func=main_analyze)

    graph_parser = subparsers.add_parser("graph")
    graph_parser.add_argument(
        "--cloudinit-log-path",
        default=Path("/var/log/cloud-init.log"),
        help="cloudinit logs path, use 'local' to fetch directly",
        type=Path,
    )
    graph_parser.add_argument(
        "--filter-conditional-result-no",
        help="Filter services that are not started due to conditional",
        action="store_true",
    )
    graph_parser.add_argument(
        "--filter-service",
        help="Filter services by name",
        default=[],
        action="extend",
        nargs="+",
    )
    graph_parser.add_argument(
        "--service",
        help="service to query dependencies for",
        default="sshd.service",
    )
    graph_parser.set_defaults(func=main_graph)

    args = parser.parse_args()

    if args.debug:
        _init_logger(logging.DEBUG)
    else:
        _init_logger(logging.INFO)

    args.output.mkdir(exist_ok=True, parents=True)
    ssh = configure_ssh(args)

    args.func(args, ssh)


if __name__ == "__main__":
    main()
