#!/usr/bin/env python3

import logging
import os
from pathlib import Path
from typing import List, Optional

import azure.mgmt.network.models
from azure.identity import AzureCliCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient

logger = logging.getLogger(__name__)


class Azure:
    def __init__(self) -> None:
        self.credential = AzureCliCredential()
        self.subscription_id = os.environ["AZURE_SUBSCRIPTION_ID"]
        self.resource_client = ResourceManagementClient(
            self.credential, self.subscription_id, polling_interval=1
        )
        self.network_client = NetworkManagementClient(
            self.credential, self.subscription_id, polling_interval=1
        )
        self.compute_client = ComputeManagementClient(
            self.credential, self.subscription_id, polling_interval=1
        )

    def nic_create(
        self, name: str, *, public_ip, rg, subnet, ip_config_name: Optional[str] = None
    ):
        if not ip_config_name:
            ip_config_name = name + "-ip"

        poller = self.network_client.network_interfaces.begin_create_or_update(
            rg.name,
            name,
            {
                "location": rg.location,
                "ip_configurations": [
                    {
                        "name": ip_config_name,
                        "subnet": {"id": subnet.id},
                        "public_ip_address": {"id": public_ip.id},
                    }
                ],
            },
        )
        nic = poller.result()
        logger.debug("Created nic: %r", vars(nic))
        return nic

    def nsg_create(self, name: str, *, rg, restrict_ssh_ip: Optional[str] = None):
        if not restrict_ssh_ip:
            restrict_ssh_ip = "*"

        params = azure.mgmt.network.models.NetworkSecurityGroup(
            location=rg.location,
            security_rules=[
                azure.mgmt.network.models.SecurityRule(
                    name="ssh",
                    access=azure.mgmt.network.models.SecurityRuleAccess.allow,
                    description="ssh",
                    destination_address_prefix="*",
                    destination_port_range="22",
                    direction=azure.mgmt.network.models.SecurityRuleDirection.inbound,
                    priority=500,
                    protocol=azure.mgmt.network.models.SecurityRuleProtocol.tcp,
                    source_address_prefix=restrict_ssh_ip,
                    source_port_range="*",
                ),
            ],
        )

        poller = self.network_client.network_security_groups.begin_create_or_update(
            rg.name,
            name,
            params,
        )
        nsg = poller.result()
        logger.debug("Created nsg: %r", vars(nsg))
        return nsg

    def public_ip_create(self, name: str, *, rg):
        params = {
            "location": rg.location,
            "sku": {"name": "Standard"},
            "public_ip_allocation_method": "Static",
            "public_ip_address_version": "IPV4",
        }
        poller = self.network_client.public_ip_addresses.begin_create_or_update(
            rg.name, name, params
        )
        public_ip = poller.result()
        logger.debug("Created public ip: %r", vars(public_ip))
        return public_ip

    def rg_create(self, name: str, *, location: str):
        params = {"location": location, "tags": {"environment": "test"}}
        rg = self.resource_client.resource_groups.create_or_update(name, params)

        logger.debug("Created resource group: %r", vars(rg))
        return rg

    def rg_delete(self, rg, wait: bool = True) -> None:
        poller = self.resource_client.resource_groups.begin_delete(
            rg.name,
            force_deletion_types="Microsoft.Compute/virtualMachines,Microsoft.Compute/virtualMachineScaleSets",
        )
        if not wait:
            return

        poller.result()

    def subnet_create(self, name: str, *, address_prefix: str, rg, nsg, vnet):
        params = {"address_prefix": address_prefix}
        if nsg:
            params["network_security_group"] = nsg

        poller = self.network_client.subnets.begin_create_or_update(
            rg.name, vnet.name, name, params
        )
        subnet = poller.result()
        logger.debug("Created subnet: %r", vars(subnet))
        return subnet

    def vnet_create(self, name: str, *, address_prefixes: List[str], rg):
        poller = self.network_client.virtual_networks.begin_create_or_update(
            rg.name,
            name,
            {
                "location": rg.location,
                "address_space": {"address_prefixes": address_prefixes},
            },
        )
        vnet = poller.result()
        logger.debug("Created vnet: %r", vars(vnet))
        return vnet

    def vm_create(
        self,
        name: str,
        *,
        image: str,
        nics,
        rg,
        admin_username: str,
        admin_password: Optional[str],
        ssh_pubkey_path: Optional[Path],
        vm_size: str,
    ):
        params = {
            "location": rg.location,
            "storage_profile": {"image_reference": {}},
            "hardware_profile": {"vm_size": vm_size},
            "diagnostics_profile": {"boot_diagnostics": {"enabled": True}},
            "os_profile": {
                "computer_name": name,
                "admin_username": admin_username,
                "linux_configuration": {},
            },
            "network_profile": {
                "network_interfaces": [
                    {
                        "id": nic.id,
                    }
                    for nic in nics
                ]
            },
        }

        os_profile = params["os_profile"]
        linux_configuration = os_profile["linux_configuration"]

        if admin_password:
            os_profile["admin_password"] = admin_password
            linux_configuration["disable_password_authentication"] = False
        else:
            linux_configuration["disable_password_authentication"] = True

        if ssh_pubkey_path:
            linux_configuration["ssh"] = {
                "public_keys": [
                    {
                        "path": f"/home/{admin_username}/.ssh/authorized_keys",
                        "key_data": ssh_pubkey_path.read_text(),
                    }
                ]
            }

        image = image.lower()
        image_reference = params["storage_profile"]["image_reference"]
        if "/communitygalleries/" in image:
            image_reference["communityGalleryImageId"] = image
        elif "/sharedgalleries/" in image:
            image_reference["sharedGalleryImageId"] = image
        elif ":" in image:
            publisher, offer, sku, version = image.split(":")
            image_reference["publisher"] = publisher
            image_reference["offer"] = offer
            image_reference["sku"] = sku
            image_reference["version"] = version

            if publisher in ["almalinux", "kinvolk"]:
                params["plan"] = {
                    "name": sku,
                    "product": offer,
                    "publisher": publisher,
                    "sku": sku,
                }

        logger.debug("Creating VM with params: %r", params)
        poller = self.compute_client.virtual_machines.begin_create_or_update(
            rg.name, name, params
        )
        vm = poller.result()
        logger.debug(
            "Created vm: %r",
            vars(vm),
        )
        return vm

    def create_standard_vm(
        self,
        *,
        image: str,
        name: str,
        rg,
        num_nics: int,
        admin_username: str,
        admin_password: Optional[str],
        restrict_ssh_ip: Optional[str],
        ssh_pubkey_path: Path,
        vm_size: str,
    ):
        nic_name = name + "-nic"
        nsg_name = name + "-nsg"
        public_ip_name = name + "-ip"
        subnet_name = name + "-subnet"
        vnet_name = name + "-vnet"
        admin_username = admin_username
        admin_password = admin_password

        public_ips = [
            self.public_ip_create(f"{public_ip_name}{i}", rg=rg)
            for i in range(num_nics)
        ]
        vnet = self.vnet_create(vnet_name, rg=rg, address_prefixes=["10.0.0.0/16"])
        nsg = self.nsg_create(nsg_name, restrict_ssh_ip=restrict_ssh_ip, rg=rg)
        subnet = self.subnet_create(
            subnet_name, nsg=nsg, rg=rg, vnet=vnet, address_prefix="10.0.0.0/24"
        )
        nics = [
            self.nic_create(
                f"{nic_name}{i}", rg=rg, public_ip=public_ips[i], subnet=subnet
            )
            for i in range(num_nics)
        ]
        vm = self.vm_create(
            name,
            rg=rg,
            nics=nics,
            admin_username=admin_username,
            admin_password=admin_password,
            image=image,
            ssh_pubkey_path=ssh_pubkey_path,
            vm_size=vm_size,
        )
        return vm, public_ips