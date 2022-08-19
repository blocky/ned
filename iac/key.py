import os
from dataclasses import dataclass
from pprint import pformat
from typing import TypeVar

import botocore.client
import botocore.exceptions

import iac.aws
from iac.aws import DEPLOYMENT_TAG, SEQUENCER_TAG
from iac.exception import IACWarning, IACError, IACErrorCode


class IACKeyError(IACError):
    pass


class IACKeyWarning(IACWarning):
    pass


KeySelf = TypeVar("KeySelf", bound="Key")


@dataclass(frozen=True)
class Key:
    name: str
    tags: [iac.aws.Tag] = None

    @staticmethod
    def from_aws_key_pair(key_pair: dict) -> KeySelf:
        return Key(
            name=key_pair["KeyName"],
            tags=key_pair["Tags"],
        )

    @staticmethod
    def to_dict(instance: KeySelf) -> dict:
        return instance.__dict__


@dataclass(frozen=True)
class KeyFileManager:
    folder: str

    def _file_name(self, key_name: str) -> str:
        return os.path.join(self.folder, key_name + ".pem")

    def create(self, key_name: str, key_material: str) -> str:
        key_fn = self._file_name(key_name)
        with open(key_fn, mode="x", encoding="utf-8") as file:
            file.write(key_material)
        return key_fn

    def delete(self, key_name: str) -> str:
        key_fn = self._file_name(key_name)
        os.remove(key_fn)
        return key_fn


def describe_key_pairs(ec2: botocore.client.BaseClient, key_name: str = None) -> dict:
    filters = [
        {"Name": "tag:" + DEPLOYMENT_TAG, "Values": [SEQUENCER_TAG]},
    ]

    if key_name is None:
        return ec2.describe_key_pairs(Filters=filters)

    try:
        return ec2.describe_key_pairs(KeyNames=[key_name], Filters=filters)
    except botocore.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "InvalidKeyPair.NotFound":
            raise IACKeyWarning(IACErrorCode.NO_SUCH_KEY, pformat(exc.response)) from exc
        raise exc


def create_key_pair(
    ec2: botocore.client.BaseClient,
    kfm: KeyFileManager,
    key_name: str,
) -> Key:
    try:
        res = ec2.create_key_pair(
            KeyName=key_name,
            KeyType="rsa",
            KeyFormat="pem",
            TagSpecifications=[
                {
                    "ResourceType": "key-pair",
                    "Tags": [
                        {"Key": DEPLOYMENT_TAG, "Value": SEQUENCER_TAG},
                    ],
                },
            ],
        )
    except botocore.exceptions.ClientError as exc:
        if exc.response["Error"]["Code"] == "InvalidKeyPair.Duplicate":
            raise IACKeyWarning(IACErrorCode.DUPLICATE_KEY, pformat(exc.response)) from exc
        raise exc

    kfm.create(key_name, res["KeyMaterial"])

    return Key(name=res["KeyName"])


def delete_key_pair(
    ec2: botocore.client.BaseClient,
    kfm: KeyFileManager,
    key_name: str,
) -> Key:
    res = describe_key_pairs(ec2, key_name)

    if len(res["KeyPairs"]) != 1:
        raise IACKeyError(
            IACErrorCode.NO_SUCH_KEY,
            f"Found not exactly one key {key_name} to delete",
        )

    ec2.delete_key_pair(KeyName=key_name)

    try:
        res = describe_key_pairs(ec2, key_name)
        if len(res["KeyPairs"]) != 0:
            raise IACKeyError(
                IACErrorCode.KEY_DELETE_FAIL,
                f"Key '{key_name}' was not deleted",
            )
    except IACKeyWarning as exc:
        if exc.error_code != IACErrorCode.NO_SUCH_KEY:
            raise exc

    kfm.delete(key_name)

    return Key.from_aws_key_pair(res["KeyPairs"][0])


def list_key_pairs(ec2: botocore.client.BaseClient) -> [Key]:
    res = describe_key_pairs(ec2)
    return [Key.from_aws_key_pair(key_pair) for key_pair in res["KeyPairs"]]
