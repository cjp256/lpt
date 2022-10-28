import argparse
import dataclasses
import datetime
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

import paramiko

from .analyze import analyze_events
from .cloudinit import CloudInit
from .clouds.azure import Azure
from .clouds.keys import generate_ssh_keys
from .graph import ServiceGraph
from .journal import Journal
from .ssh import SSH
from .systemd import Systemctl, Systemd

logger = logging.getLogger("lpt")


@dataclasses.dataclass
class SshManager:
    proxy_host: Optional[str] = None
    proxy_user: Optional[str] = None

    def connect(self, *, host: str, user: str) -> Optional[SSH]:
        if not host:
            return None

        while True:
            try:
                ssh = SSH(
                    host=host,
                    user=user,
                    proxy_host=self.proxy_host,
                    proxy_user=self.proxy_user,
                )
                ssh.connect()
                break
            except paramiko.ssh_exception.AuthenticationException as exc:
                logger.debug("failed auth: %r", exc)
                continue
            except paramiko.ssh_exception.NoValidConnectionsError as exc:
                logger.debug("failed to connect: %r", exc)
                continue
            except paramiko.ssh_exception.SSHException as exc:
                logger.debug("failed to connect: %r", exc)
                continue

        return ssh


def _init_logger(log_level: int):
    logging.basicConfig(level=log_level)
    logger.setLevel(log_level)
    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d|%(levelname)s|%(name)s:%(module)s:%(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(log_level)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Cleanup logging
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    logging.getLogger("paramiko").propagate = False
    logging.getLogger("urllib3").handlers = []
    logging.getLogger("urllib3").addHandler(handler)
    logging.getLogger("urllib3").propagate = False


def load_cloudinit(args, ssh: Optional[SSH]) -> List[CloudInit]:
    if ssh:
        return CloudInit.load_remote(ssh, output_dir=args.output)

    return CloudInit.load(args.cloudinit_log_path, output_dir=args.output)


def load_journal(args, ssh: Optional[SSH]) -> List[Journal]:
    if ssh:
        return Journal.load_remote(ssh, output_dir=args.output)

    return Journal.load(journal_path=args.journal_path, output_dir=args.output)


def main_analyze(args, ssh_mgr: SshManager) -> None:
    ssh = ssh_mgr.connect(host=args.ssh_host, user=args.ssh_user)

    cloudinits = load_cloudinit(args, ssh)
    journals = load_journal(args, ssh)
    event_data = analyze_events(
        journals=journals,
        cloudinits=cloudinits,
        boot=args.boot,
        event_types=args.event_type,
    )
    print(json.dumps(vars(event_data), indent=4))


def main_analyze_cloudinit(args, ssh_mgr: SshManager) -> None:
    ssh = ssh_mgr.connect(host=args.ssh_host, user=args.ssh_user)

    cloudinits = load_cloudinit(args, ssh)
    event_data = analyze_events(
        journals=[], cloudinits=cloudinits, boot=args.boot, event_types=args.event_type
    )
    print(json.dumps(vars(event_data), indent=4))


def main_analyze_journal(args, ssh_mgr: SshManager) -> None:
    ssh = ssh_mgr.connect(host=args.ssh_host, user=args.ssh_user)

    journals = load_journal(args, ssh)
    event_data = analyze_events(
        journals=journals, cloudinits=[], boot=args.boot, event_types=args.event_type
    )
    print(json.dumps(vars(event_data), indent=4))


def main_graph(args, ssh_mgr: SshManager) -> None:
    ssh = ssh_mgr.connect(host=args.ssh_host, user=args.ssh_user)

    cloudinits = load_cloudinit(args, ssh)
    if cloudinits:
        cloudinit = cloudinits[-1]
        frames = cloudinit.get_frames()
    else:
        frames = []

    if ssh:
        systemd = Systemd.load_remote(ssh, output_dir=args.output)
        units = Systemctl.load_units_remote(ssh, output_dir=args.output)
    else:
        systemd = Systemd.load(output_dir=args.output)
        units = Systemctl.load_units(output_dir=args.output)

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


def main_launch_azure_instance(args, ssh_mgr: SshManager) -> None:
    name = datetime.datetime.utcnow().strftime("t%m%d%Y%H%M%S%f")
    rg_name = args.rg
    vm_name = f"ephemeral-{name}"

    azure = Azure()
    rg = azure.rg_create(rg_name, location=args.location)
    logger.debug("RG created: %r", vars(rg))

    if args.ssh_public_key:
        pub_key = args.ssh_public_key
        priv_key = None
    else:
        key_dir = Path(tempfile.TemporaryDirectory().name)
        pub_key, priv_key = generate_ssh_keys(key_dir, "testkey")

    for image in args.images:
        if "arm64" in image:
            vm_size = "Standard_D4plds_v5"
        else:
            vm_size = "Standard_DS1_v2"

        vm, public_ips = azure.launch_vm(
            image=image,
            name=vm_name,
            num_nics=1,
            rg=rg,
            vm_size=vm_size,
            ssh_pubkey_path=pub_key,
            admin_username=args.admin_username,
            admin_password=None,
            restrict_ssh_ip=args.restrict_ssh_ip,
        )

        logger.info(
            "Created: %r %r %r", vars(rg), vars(vm), [p.ip_address for p in public_ips]
        )

        ssh = ssh_mgr.connect(host=public_ips[0].ip_address, user=args.admin_username)
        logger.info("Connected: %s@%s", args.admin_username, public_ips[0].ip_address)

        cloudinits = load_cloudinit(args, ssh)
        journals = load_journal(args, ssh)
        event_data = analyze_events(
            journals=journals,
            cloudinits=cloudinits,
            boot=True,
            event_types=args.event_type,
        )
        print(json.dumps(vars(event_data), indent=4))


def main():
    all_arguments = {
        "--boot": {"help": "only analyze this last boot", "action": "store_true"},
        "--cloudinit-log-path": {
            "default": "/var/log/cloud-init.log",
            "help": "cloudinit logs path, use 'local' to fetch directly",
            "type": Path,
        },
        "--debug": {"help": "output debug info", "action": "store_true"},
        "--event-type": {
            "default": [],
            "help": "event types to output",
            "action": "extend",
            "nargs": "+",
        },
        "--filter-conditional-result-no": {
            "help": "Filter services that are not started due to conditional",
            "action": "store_true",
        },
        "--filter-service": {
            "help": "Filter services by name",
            "default": [],
            "action": "extend",
            "nargs": "+",
        },
        "--journal-path": {
            "default": "/var/log/journal",
            "help": "journal directory",
            "type": Path,
        },
        "--output": {
            "default": Path("lpt-output"),
            "help": "output directory to store artifacts",
            "type": Path,
        },
        "--ssh-host": {"help": "collect data via ssh"},
        "--ssh-user": {"help": "collect data via ssh"},
        "--ssh-proxy-host": {"help": "use ssh proxy as jump host"},
        "--ssh-proxy-user": {"help": "use ssh proxy as jump host"},
    }

    parser = argparse.ArgumentParser(add_help=True)

    parser.set_defaults(func=lambda x: main_help(parser, x))

    for opt in [
        "--debug",
        "--output",
        "--ssh-proxy-host",
        "--ssh-proxy-user",
    ]:
        parser.add_argument(opt, **all_arguments[opt])

    subparsers = parser.add_subparsers()

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.set_defaults(func=main_analyze)
    for opt in [
        "--boot",
        "--cloudinit-log-path",
        "--event-type",
        "--journal-path",
        "--ssh-host",
        "--ssh-user",
    ]:
        analyze_parser.add_argument(opt, **all_arguments[opt])

    analyze_parser = subparsers.add_parser("analyze-cloudinit")
    analyze_parser.set_defaults(func=main_analyze_cloudinit)
    for opt in [
        "--boot",
        "--cloudinit-log-path",
        "--event-type",
        "--ssh-host",
        "--ssh-user",
    ]:
        analyze_parser.add_argument(opt, **all_arguments[opt])

    analyze_parser = subparsers.add_parser("analyze-journal")
    analyze_parser.set_defaults(func=main_analyze_journal)
    for opt in ["--boot", "--event-type", "--journal-path", "--ssh-host", "--ssh-user"]:
        analyze_parser.add_argument(opt, **all_arguments[opt])

    graph_parser = subparsers.add_parser("graph")
    graph_parser.set_defaults(func=main_graph)
    for opt in [
        "--cloudinit-log-path",
        "--filter-conditional-result-no",
        "--filter-service",
    ]:
        graph_parser.add_argument(opt, **all_arguments[opt])

    graph_parser.add_argument(
        "service",
        metavar="service",
        help="service to query dependencies for",
        default="sshd.service",
    )

    launch_parser = subparsers.add_parser("launch-azure-instance")
    launch_parser.set_defaults(func=main_launch_azure_instance)
    for opt in ["--boot", "--event-type"]:
        launch_parser.add_argument(opt, **all_arguments[opt])
    launch_parser.add_argument(
        "images",
        metavar="image",
        help="os image to launch",
        nargs="+",
    )
    launch_parser.add_argument(
        "--rg",
        help="resource group name",
        required=True,
    )
    launch_parser.add_argument(
        "--location",
        help="location to launch in",
        default="eastus",
    )
    launch_parser.add_argument(
        "--admin-username",
        help="admin username",
        default="testadmin",
    )
    launch_parser.add_argument(
        "--restrict-ssh-ip",
        help="secure NSG with specific IP for SSH",
    )
    launch_parser.add_argument(
        "--ssh-public-key",
        help="public key",
        type=Path,
    )
    launch_parser.set_defaults(func=main_launch_azure_instance)

    args = parser.parse_args()

    if args.debug:
        _init_logger(logging.DEBUG)
    else:
        _init_logger(logging.INFO)

    args.output.mkdir(exist_ok=True, parents=True)

    ssh_mgr = SshManager(proxy_host=args.ssh_proxy_host, proxy_user=args.ssh_proxy_user)
    args.func(args, ssh_mgr)


if __name__ == "__main__":
    main()
