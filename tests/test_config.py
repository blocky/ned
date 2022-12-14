import pytest

import ned
from ned.ned import sample_config_file_name


def expected_config_from_fixture():
    return ned.Config(
        cred_file="my-cred-file.csv",
        secrets_folder="my-secrets-folder",
        instance_name="my-instance",
        key_name="my-key",
        region="my-region",
        security_group="my-security-group",
        instance_kind="nitro",
        fqdn="my-fqdn",
    )


def test_config__from_toml__with_context_happy_path(config_file_name):
    config = ned.Config.from_toml(config_file_name, sample_config_file_name())
    assert config == expected_config_from_fixture()


def test_config__from_toml__with_context_file_not_found():
    with pytest.raises(FileNotFoundError):
        ned.Config.from_toml("not-a-file", sample_config_file_name())


def test_config__from_toml__no_context_with_user_happy_path(config_file_name):
    config = ned.Config.from_toml(None, config_file_name)
    assert config == expected_config_from_fixture()


def test_config__from_toml__no_context_with_user_file_not_found():
    config = ned.Config.from_toml(None, "not-a-file")
    assert config == ned.Config()


def test_config__from_toml__bad_format(config_file_invalid):
    config = ned.Config.from_toml(None, config_file_invalid)
    assert config == ned.Config()


def test_config__from_kwargs():
    region = "mars"
    access_key = "abc"
    secret_key = "123"

    config = ned.Config.from_kwargs(
        **{
            "region": region,
            "access_key": access_key,
            "secret_key": secret_key,
            "random": "junk",
        }
    )

    assert config.region == region
    assert config.access_key == access_key
    assert config.secret_key == secret_key
    assert config.cred_file is None
    assert config.key_name is None
    assert config.secrets_folder is None
    assert config.instance_name is None
    assert config.instance_kind is None
    assert config.security_group is None
