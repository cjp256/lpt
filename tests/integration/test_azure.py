#!/usr/bin/env python3

import datetime
import json
import logging
import os
import subprocess
import warnings
from pathlib import Path

import pytest
import whatismyip  # type: ignore

from lpt.analyze import analyze_events
from lpt.cloudinit import CloudInit
from lpt.clouds.azure import Azure
from lpt.journal import Journal
from lpt.ssh import SSH
from lpt.systemd import Systemd

logger = logging.getLogger(__name__)

if os.environ.get("LPT_TEST_AZURE_IMAGES") != "1":
    pytest.skip("skipping azure integration tests", allow_module_level=True)

TEST_USERNAME = "testuser"


def warn(warning: str) -> None:
    warnings.warn(UserWarning(warning))


@pytest.fixture(autouse=True)
def cleanup_logging():
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    logging.getLogger("paramiko").propagate = False


@pytest.fixture
def restrict_ssh_source_ip():
    try:
        yield os.environ["LPT_TESTS_AZURE_RESTRICT_SOURCE_IP"]
    except KeyError:
        yield whatismyip.whatismyipv4()


@pytest.fixture
def azure():
    yield Azure()


@pytest.fixture
def rg(azure, rg_location, rg_name):
    rg = azure.rg_create(rg_name, location=rg_location)
    try:
        yield rg
    finally:
        azure.rg_delete(rg, wait=False)


@pytest.fixture
def rg_location():
    yield os.environ.get("LPT_TESTS_AZURE_LOCATION", "eastus")


@pytest.fixture
def common_name():
    yield datetime.datetime.utcnow().strftime("t%m%d%Y%H%M%S%f")


@pytest.fixture
def rg_name(common_name):
    yield f"deleteme-{common_name}-rg"


@pytest.fixture
def vm_name(common_name):
    yield f"deleteme-{common_name}-vm"


@pytest.fixture
def ssh_keys(tmp_path: Path, vm_name: str):
    tmp_path.mkdir(exist_ok=True, parents=True)
    public_key = tmp_path / (vm_name + ".pub")
    private_key = tmp_path / vm_name

    subprocess.run(
        ["ssh-keygen", "-f", private_key.as_posix(), "-N", "", "-t", "rsa"],
        check=True,
        capture_output=True,
    )
    logger.debug("created ssh key: %s %s", public_key, private_key)

    yield public_key, private_key

    public_key.unlink()
    private_key.unlink()


@pytest.fixture
def ssh(ssh_keys):
    proxy_host = os.environ.get("LPT_TESTS_AZURE_SSH_PROXY_HOST")
    proxy_user = os.environ.get("LPT_TESTS_AZURE_SSH_PROXY_USER")
    _, private_key = ssh_keys
    yield SSH(
        host=None,
        user=TEST_USERNAME,
        proxy_host=proxy_host,
        proxy_user=proxy_user,
        private_key=private_key,
    )


@pytest.mark.parametrize(
    "image",
    [
        "almalinux:almalinux:8_5-gen2:latest",
        "almalinux:almalinux:8_5:latest",
        "canonical:0001-com-ubuntu-minimal-bionic:minimal-18_04-lts-gen2:latest",
        "canonical:0001-com-ubuntu-minimal-bionic:minimal-18_04-lts:latest",
        "canonical:0001-com-ubuntu-minimal-focal:minimal-20_04-lts-gen2:latest",
        "canonical:0001-com-ubuntu-minimal-focal:minimal-20_04-lts:latest",
        "canonical:0001-com-ubuntu-minimal-jammy:minimal-22_04-lts-gen2:latest",
        "canonical:0001-com-ubuntu-minimal-jammy:minimal-22_04-lts:latest",
        "canonical:0001-com-ubuntu-server-focal:20_04-lts-arm64:latest",
        "canonical:0001-com-ubuntu-server-focal:20_04-lts-gen2:latest",
        "canonical:0001-com-ubuntu-server-focal:20_04-lts:latest",
        "canonical:0001-com-ubuntu-server-jammy:22_04-lts-arm64:latest",
        "canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:latest",
        "canonical:0001-com-ubuntu-server-jammy:22_04-lts:latest",
        "canonical:ubuntuserver:18.04-lts:latest",
        "canonical:ubuntuserver:18_04-lts-arm64:latest",
        "canonical:ubuntuserver:18_04-lts-gen2:latest",
        "debian:debian-10:10-gen2:latest",
        "debian:debian-10:10:latest",
        "debian:debian-11-arm64:11-backports:latest",
        "debian:debian-11:11-gen2:latest",
        "debian:debian-11:11:latest",
        "kinvolk:flatcar-container-linux-free:stable-gen2:latest",
        "kinvolk:flatcar-container-linux-free:stable:latest",
        "microsoftcblmariner:cbl-mariner:1-gen2:latest",
        "microsoftcblmariner:cbl-mariner:cbl-mariner-1:latest",
        "microsoftcblmariner:cbl-mariner:cbl-mariner-2-arm64:latest",
        "microsoftcblmariner:cbl-mariner:cbl-mariner-2-gen2:latest",
        "microsoftcblmariner:cbl-mariner:cbl-mariner-2:latest",
        "openlogic:centos:7_9-arm64:latest",
        "openlogic:centos:7_9-gen2:latest",
        "openlogic:centos:7_9:latest",
        "oracle:oracle-linux:ol79-gen2:latest",
        "oracle:oracle-linux:ol79:latest",
        "oracle:oracle-linux:ol84-lvm-gen2:latest",
        "oracle:oracle-linux:ol84-lvm:latest",
        "redhat:rhel-arm64:8_6-arm64:latest",
        "redhat:rhel:7-lvm:latest",
        "redhat:rhel:79-gen2:latest",
        "redhat:rhel:7_9:latest",
        "redhat:rhel:7lvm-gen2:latest",
        "redhat:rhel:8-lvm-gen2:latest",
        "redhat:rhel:8-lvm:latest",
        "redhat:rhel:8.1:latest",
        "redhat:rhel:8.2:latest",
        "redhat:rhel:81gen2:latest",
        "redhat:rhel:82gen2:latest",
        "redhat:rhel:84-gen2:latest",
        "redhat:rhel:85-gen2:latest",
        "redhat:rhel:86-gen2:latest",
        "redhat:rhel:8_4:latest",
        "redhat:rhel:8_5:latest",
        "redhat:rhel:8_6:latest",
        "redhat:rhel:9-lvm-gen2:latest",
        "redhat:rhel:9-lvm:latest",
        "redhat:rhel:90-gen2:latest",
        "redhat:rhel:9_0:latest",
        "suse:sles-12-sp5:gen1:latest",
        "suse:sles-12-sp5:gen2:latest",
        "suse:sles-15-sp2:gen2:latest",
        "suse:sles-15-sp3:gen1:latest",
        "suse:sles-15-sp3:gen2:latest",
        "suse:sles-15-sp4-arm64:gen2:latest",
        "suse:sles-15-sp4:gen2:latest",
    ],
)
def test_azure_instances(
    azure, image, restrict_ssh_source_ip, rg, ssh, ssh_keys, vm_name
):
    public_key, _ = ssh_keys

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
        ssh_pubkey_path=public_key,
        admin_username=TEST_USERNAME,
        admin_password=None,
        restrict_ssh_ip=restrict_ssh_source_ip,
    )

    host = public_ips[0].ip_address
    ssh.host = host
    ssh.user = TEST_USERNAME
    ssh.connect_with_retries()
    logger.info("Connected: %s@%s", TEST_USERNAME, public_ips[0].ip_address)

    try:
        system_status = ssh.wait_for_system_ready()
    except ssh.SystemReadyTimeout as error:
        system_status = error.status
        warn(f"Systemd timed out for image={image} (status={system_status})")

    output_dir = Path("/tmp", "lpt-tests", f"{image.replace(':', '_')}-{vm_name}")
    output_dir.mkdir(exist_ok=True, parents=True)

    cloudinits = CloudInit.load_remote(ssh, output_dir=output_dir)
    if image.startswith("kinvolk"):
        assert len(cloudinits) == 0
    else:
        assert len(cloudinits) > 0

    journals = Journal.load_remote(ssh, output_dir=output_dir)
    assert len(journals) > 0

    systemd = Systemd.load_remote(ssh, output_dir=output_dir)
    assert systemd

    event_data = analyze_events(
        journals=journals,
        cloudinits=cloudinits,
        systemd=systemd,
        boot=True,
        event_types=None,
    )

    out = output_dir / "event_data.json"
    out.write_text(json.dumps(vars(event_data), indent=4))

    # Raise warnings to tester.
    for warning in event_data.warnings:
        warn(f"warning for image={image}: {warning!r}")

    # Verify sample of cloud-init events.
    if not image.startswith("kinvolk"):
        for module in ["config-disk_setup", "config-growpart"]:
            events = [
                e
                for e in event_data.events
                if e["label"] == "CLOUDINIT_FRAME"
                and e["source"] == "cloudinit"
                and e["module"] == module
            ]
            assert len(events) > 0, f"missing events with label={label}"

    # Verify sample of journal events.
    for label in ["KERNEL_BOOT", "SYSTEMD_STARTED", "SSH_ACCEPTED_CONNECTION"]:
        events = [
            e
            for e in event_data.events
            if e["label"] == label and e["source"] == "journal"
        ]

        # Warn if kernel boot is missing, otherwise assert events are present.
        if len(events) == 0 and label == "KERNEL_BOOT":
            warn(f"missing events with for image={image} (label={label})")
        else:
            assert (
                len(events) > 0
            ), f"missing events with for image={image} (label={label})"

    # Verify sample of systemd events.
    for unit in ["local-fs.target", "basic.target"]:
        events = [
            e
            for e in event_data.events
            if e["label"] == "SYSTEMD_UNIT"
            and e["source"] == "systemd"
            and e["unit"] == unit
        ]

        assert len(events) > 0, f"missing events with for image={image} (unit={unit})"

    # Verify system status is good.
    if system_status != "running":
        warn(f"system degraded for image={image} (status={system_status})")
