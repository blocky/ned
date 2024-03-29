import socket
import subprocess  # nosec
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

import botocore.client

import ned.aws
from ned.aws import DEPLOYMENT_TAG, SEQUENCER_TAG
from ned.exception import NEDError, NEDWarning, NEDErrorCode


class NEDInstanceError(NEDError):
    pass


class NEDInstanceWarning(NEDWarning):
    pass


InstanceKindSelf = TypeVar("InstanceKindSelf", bound="InstanceKind")


class InstanceKind(Enum):
    STANDARD = "standard"
    NITRO = "nitro"

    @staticmethod
    def from_str(kind: str) -> InstanceKindSelf:
        match kind.lower():
            case "standard":
                return InstanceKind.STANDARD
            case "nitro":
                return InstanceKind.NITRO
            case _:
                raise NEDInstanceError(
                    NEDErrorCode.INSTANCE_UNKNOWN_KIND,
                    f"Cannot create instance kind from '{kind}'",
                )


InstanceSelf = TypeVar("InstanceSelf", bound="Instance")


@dataclass(frozen=True)
# pylint: disable = too-many-instance-attributes
class Instance:
    name: str
    state: str
    id: str = None
    key_name: str = None
    tags: [ned.aws.Tag] = None
    public_dns_name: str = None
    public_ip_address: str = None
    nitro: bool = None

    @staticmethod
    def from_aws_instance(inst: dict) -> InstanceSelf:
        tags = inst["Tags"]
        name = next((t["Value"] for t in tags if t["Key"] == "Name"), None)
        return Instance(
            name=name,
            id=inst["InstanceId"],
            state=inst["State"]["Name"],
            key_name=inst["KeyName"],
            tags=tags,
            public_dns_name=inst.get("PublicDnsName", None),
            public_ip_address=inst.get("PublicIpAddress", None),
            nitro=inst["EnclaveOptions"]["Enabled"],
        )

    @staticmethod
    def to_dict(instance: InstanceSelf) -> dict:
        return instance.__dict__


def describe_instances(
    ec2: botocore.client.BaseClient,
    instance_name: str = None,
) -> [Instance]:
    filters = [
        {"Name": "tag:" + DEPLOYMENT_TAG, "Values": [SEQUENCER_TAG]},
        {"Name": "instance-state-name", "Values": ["pending", "running"]},
    ]
    if instance_name is not None:
        filters.append(
            {"Name": "tag:Name", "Values": [instance_name]},
        )

    res = ec2.describe_instances(Filters=filters)

    return list(
        Instance.from_aws_instance(inst) for r in res["Reservations"] for inst in r["Instances"]
    )


def _validate_running(instances: [Instance], instance_name: str):
    if len(instances) == 0:
        raise NEDInstanceWarning(
            NEDErrorCode.INSTANCE_MISSING,
            f"Instance '{instance_name}' is not running",
        )


def _validate_not_multiple(instances: [Instance], instance_name: str):
    if len(instances) > 1:
        raise NEDInstanceError(
            NEDErrorCode.INSTANCE_NAME_COLLISION,
            f"More than one instance {instance_name} exists",
        )


def _ec2_config(
    kind: InstanceKind,
    instance_name: str,
    key_name: str,
    security_group: str,
) -> dict:
    definition = {
        "ImageId": "ami-08e4e35cccc6189f4",
        "MaxCount": 1,
        "MinCount": 1,
        "KeyName": key_name,
        "SecurityGroupIds": [security_group],
        "TagSpecifications": [
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": DEPLOYMENT_TAG, "Value": SEQUENCER_TAG},
                    {"Key": "Name", "Value": instance_name},
                ],
            },
        ],
    }

    instance_type_key = "InstanceType"
    match kind:
        case InstanceKind.STANDARD:
            definition[instance_type_key] = "t2.micro"
        case InstanceKind.NITRO:
            definition[instance_type_key] = "c5a.xlarge"
            definition["EnclaveOptions"] = {"Enabled": True}
        case _:
            raise NEDInstanceError(
                NEDErrorCode.INSTANCE_UNKNOWN_KIND,
                f"Unknown instance kind '{kind}'",
            )
    return definition


class InstanceBarrier:
    def wait(self, inst: Instance) -> Instance:
        return inst


@dataclass(frozen=True)
class InstanceReadyBarrier(InstanceBarrier):
    ec2: botocore.client.BaseClient
    sleep_time: float = 5
    retry_count: int = 20

    def _is_ready(self, inst: Instance) -> bool:
        if inst.state != "running":
            self._warn(f'Instance state is "{inst.state}", waiting for "running"')
            return False

        try:
            resolved_ip = socket.gethostbyname(inst.public_dns_name)
        except socket.gaierror as exc:
            self._warn(f"Host lookup error: {exc}")
            return False

        if inst.public_ip_address != resolved_ip:
            self._warn(
                f"Instance resolved IP is {resolved_ip}, " f"but should be {inst.public_ip_address}"
            )
            return False

        if not self._ping(inst.public_ip_address):
            self._warn(f"Cannot ping {inst.public_ip_address}")
            return False

        return True

    def _ping(self, host: str):
        command = ["ping", "-c", "1", host]
        # allow ping through subprocess with nosec
        return subprocess.call(command, stdout=subprocess.DEVNULL) == 0  # nosec

    def _warn(self, msg: str, out=sys.stderr) -> None:
        out.write(f"**Warning** {msg}\n")

    def wait(self, inst: Instance) -> Instance:
        ready = self._is_ready(inst)

        remaining_attempts = self.retry_count
        while not ready and remaining_attempts > 0:
            n = self.retry_count  # pylint: disable = invalid-name
            k = n - remaining_attempts + 1
            self._warn(f"Checking again {k}/{n}")
            time.sleep(self.sleep_time)
            inst = fetch_instance(self.ec2, inst.name)
            ready = self._is_ready(inst)
            remaining_attempts -= 1

        if not ready:
            raise NEDInstanceError(
                NEDErrorCode.INSTANCE_NOT_READY,
                "Instance is not ready",
            )
        return inst


def create_instance(
    ec2: botocore.client.BaseClient,
    kind: InstanceKind,
    instance_name: str,
    key_name: str,
    security_group: str,
    barrier: InstanceBarrier = InstanceBarrier(),
) -> Instance:
    # pylint: disable = too-many-arguments
    instances = describe_instances(ec2, instance_name)
    if len(instances) != 0:
        raise NEDInstanceWarning(
            NEDErrorCode.INSTANCE_DUPLICATE,
            f"Instance '{instance_name}' already exists",
        )

    config = _ec2_config(kind, instance_name, key_name, security_group)
    res = ec2.run_instances(**config)
    inst = Instance.from_aws_instance(res["Instances"][0])

    return barrier.wait(inst)


def terminate_instance(
    ec2: botocore.client.BaseClient,
    instance_name: str,
) -> Instance:
    instances = describe_instances(ec2, instance_name)
    _validate_running(instances, instance_name)
    _validate_not_multiple(instances, instance_name)
    instance = instances[0]

    res = ec2.terminate_instances(InstanceIds=[instance.id])
    current_state = res["TerminatingInstances"][0]["CurrentState"]["Name"]
    if current_state not in {"shutting-down", "terminated"}:
        raise NEDInstanceError(
            NEDErrorCode.INSTANCE_TERMINATION_FAIL,
            f"Instance '{instance_name}' was not terminated state is '{current_state}'",
        )

    return instance


def list_instances(ec2: botocore.client.BaseClient) -> [Instance]:
    return describe_instances(ec2)


def fetch_instance(
    ec2: botocore.client.BaseClient,
    instance_name: str,
) -> Instance:
    instances = describe_instances(ec2, instance_name)
    _validate_running(instances, instance_name)
    _validate_not_multiple(instances, instance_name)
    return instances[0]
