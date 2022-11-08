import json
from os.path import join
from importlib import resources
from pathlib import Path

import click

import iac


APP_DATA_PATH = resources.path("iac", "data")
USER_DATA_PATH = join(Path.home(), ".config", "bky", "iac")
IAC_CMD_KWARGS = {
    "obj": {},
    "auto_envvar_prefix": "BKY_IAC",
}


def sample_config_file_name():
    return join(APP_DATA_PATH, "sample_config.toml")


def user_config_file_name():
    return join(USER_DATA_PATH, "config.toml")


def console(data, to_dict=None):
    out = data
    if to_dict:
        try:
            as_dict = [to_dict(d) for d in data]
        except TypeError:
            as_dict = to_dict(data)
        out = json.dumps(as_dict, indent=2)

    click.echo(out)


def fail_on_nodebug(ctx):
    if not ctx.obj["conf"].debug:
        raise click.UsageError("Cannot run command in nodebug mode")


def fail_on_debug(ctx):
    if ctx.obj["conf"].debug:
        raise click.UsageError("Cannot run command in debug mode")


class CatchAllExceptions(click.Group):
    def __call__(self, *args, **kwargs):
        try:
            return self.main(*args, **kwargs)
        except iac.IACException as exc:
            console(f"{exc.error_code.name}: {exc}")


@click.group(cls=CatchAllExceptions)
@click.option("--config-file", show_envvar=True)
@click.option("--access-key", show_envvar=True)
@click.option("--secret-key", show_envvar=True)
@click.option("--cred-file", show_envvar=True)
@click.option("--region", show_envvar=True)
@click.option("--debug/--no-debug", default=False, show_envvar=True, show_default=True)
@click.pass_context
# pylint: disable = too-many-arguments
def iac_cmd(
    ctx,
    config_file,
    access_key,
    secret_key,
    cred_file,
    region,
    debug,
):  # noqa: R0913
    conf = iac.Config.from_toml(config_file, user_config_file_name())

    conf.debug = debug or conf.debug
    conf.region = region or conf.region
    conf.access_key = access_key or conf.access_key
    conf.secret_key = secret_key or conf.secret_key
    conf.cred_file = cred_file or conf.cred_file

    creds = None
    if conf.access_key and conf.secret_key:
        creds = iac.aws.Credentials(conf.access_key, conf.secret_key)
    elif conf.cred_file:
        creds = iac.get_credentials(conf.cred_file)

    ctx.obj["client"] = iac.AWSClient(creds, conf.region) if creds else None
    ctx.obj["conf"] = conf


@click.group(name="key")
@click.option("--key-name", show_envvar=True)
@click.option("--secrets-folder", show_envvar=True)
@click.pass_context
def key_cmd(ctx, key_name, secrets_folder):
    conf = ctx.obj["conf"]

    conf.key_name = key_name or conf.key_name
    conf.secrets_folder = secrets_folder or conf.secrets_folder

    ctx.obj["conf"] = conf


@click.command(name="create")
@click.pass_context
def key_create_cmd(ctx):
    fail_on_debug(ctx)

    conf = ctx.obj["conf"]
    client = ctx.obj["client"]

    kfm = iac.KeyFileManager(conf.secrets_folder)
    key = iac.create_key_pair(client.ec2, kfm, conf.key_name)
    console(key, to_dict=iac.Key.to_dict)


@click.command(name="delete")
@click.pass_context
def key_delete_cmd(ctx):
    fail_on_debug(ctx)

    conf = ctx.obj["conf"]
    client = ctx.obj["client"]

    kfm = iac.KeyFileManager(conf.secrets_folder)
    key = iac.delete_key_pair(client.ec2, kfm, conf.key_name)
    console(key, to_dict=iac.Key.to_dict)


@click.command(name="list")
@click.pass_context
def key_list_cmd(ctx):
    fail_on_debug(ctx)

    client = ctx.obj["client"]

    keys = iac.list_key_pairs(client.ec2)
    console(keys, to_dict=iac.Key.to_dict)


@click.command(name="dbgconf")
@click.pass_context
def x_dbgconf_cmd(ctx):
    fail_on_nodebug(ctx)

    console(ctx.obj["conf"], to_dict=iac.Config.to_dict)


iac_cmd.add_command(key_cmd)
key_cmd.add_command(key_create_cmd)
key_cmd.add_command(key_delete_cmd)
key_cmd.add_command(key_list_cmd)
key_cmd.add_command(x_dbgconf_cmd)


@click.group(name="instance")
@click.option("--instance-name", show_envvar=True)
@click.option("--key-name", show_envvar=True)
@click.option("--security-group", show_envvar=True)
@click.option("--nitro/--no-nitro", default=None, show_envvar=True)
@click.pass_context
def instance_cmd(ctx, instance_name, key_name, security_group, nitro):
    conf = ctx.obj["conf"]

    conf.instance_name = instance_name or conf.instance_name
    conf.key_name = key_name or conf.key_name
    conf.security_group = security_group or conf.security_group

    IK = iac.InstanceKind
    if nitro is not None:
        conf.instance_kind = IK.NITRO.value if nitro else IK.STANDARD.value

    ctx.obj["conf"] = conf


@click.command(name="create")
@click.pass_context
def instance_create_cmd(ctx):
    fail_on_debug(ctx)

    conf = ctx.obj["conf"]
    client = ctx.obj["client"]

    instance = iac.create_instance(
        client.ec2,
        iac.InstanceKind.from_str(conf.instance_kind),
        conf.instance_name,
        conf.key_name,
        conf.security_group,
        iac.instance.InstanceRunningBarrier(client.ec2),
    )
    console(instance, to_dict=iac.Instance.to_dict)


@click.command(name="terminate")
@click.pass_context
def instance_terminate_cmd(ctx):
    fail_on_debug(ctx)

    client = ctx.obj["client"]
    instance_name = ctx.obj["conf"].instance_name

    instance = iac.terminate_instance(client.ec2, instance_name)
    console(instance, to_dict=iac.Instance.to_dict)


@click.command(name="list")
@click.pass_context
def instance_list_cmd(ctx):
    fail_on_debug(ctx)

    client = ctx.obj["client"]

    instances = iac.list_instances(client.ec2)
    console(instances, to_dict=iac.Instance.to_dict)


iac_cmd.add_command(instance_cmd)
instance_cmd.add_command(instance_create_cmd)
instance_cmd.add_command(instance_terminate_cmd)
instance_cmd.add_command(instance_list_cmd)
instance_cmd.add_command(x_dbgconf_cmd)


@click.command(name="config")
def config_cmd():
    with open(sample_config_file_name(), encoding="utf8") as handle:
        console(handle.read())


iac_cmd.add_command(config_cmd)


def remote_runner(ctx):
    conf = ctx.obj["conf"]
    client = ctx.obj["client"]

    key_file = iac.KeyFileManager(conf.secrets_folder).key_file(conf.key_name)
    instance = iac.fetch_instance(client.ec2, conf.instance_name)
    return iac.RemoteCMDRunner.from_instance_and_key_file(instance, key_file)


@click.group(name="deploy")
@click.option("--instance-name", show_envvar=True)
@click.option("--key-name", show_envvar=True)
@click.option("--secrets-folder", show_envvar=True)
@click.pass_context
def deploy_cmd(ctx, instance_name, key_name, secrets_folder):
    conf = ctx.obj["conf"]

    conf.instance_name = instance_name or conf.instance_name
    conf.key_name = key_name or conf.key_name
    conf.secrets_folder = secrets_folder or conf.secrets_folder

    ctx.obj["conf"] = conf


@click.command(name="copy")
@click.argument("file_name")
@click.pass_context
def deploy_cmd_copy(ctx, file_name):
    fail_on_debug(ctx)

    remote_runner(ctx).copy(file_name)


@click.command(name="run")
@click.argument("cmd")
@click.pass_context
def deploy_cmd_run(ctx, cmd):
    fail_on_debug(ctx)

    out = remote_runner(ctx).run(cmd)
    console(out, to_dict=iac.run_result_to_dict)


iac_cmd.add_command(deploy_cmd)
deploy_cmd.add_command(deploy_cmd_copy)
deploy_cmd.add_command(deploy_cmd_run)
deploy_cmd.add_command(x_dbgconf_cmd)


# @click.group(name="dns")
@click.command(name="dns")
@click.pass_context
def dns_cmd(ctx):
    conf = ctx.obj["conf"]
    client = ctx.obj["client"]

    dns = iac.DNSManager(client.route53)
    instance = iac.fetch_instance(client.ec2, conf.instance_name)
    # dns.create_a_record("a.b.dlm.bky.sh", instance.public_ip_address)
    dns.fetch_a_record("x.b.dlm.bky.sh")
    # dns.delete_a_record("a.b.dlm.bky.sh", instance.public_ip_address)



@click.group(name="dns")
@click.option("--instance-name", show_envvar=True)
@click.option("--host-name", show_envvar=True)
@click.pass_context
def dns_cmd(ctx, instance_name, host_name):
    conf = ctx.obj["conf"]

    conf.instance_name = instance_name or conf.instance_name
    conf.host_name = host_name or conf.host_name

    ctx.obj["conf"] = conf


@click.command(name="create")
@click.pass_context
def dns_cmd_create(ctx):
    fail_on_debug(ctx)

    conf = ctx.obj["conf"]
    client = ctx.obj["client"]

    instance = iac.fetch_instance(client.ec2, conf.instance_name)

    dns = iac.DNSManager(client.route53)
    dns.create_a_record(conf.host_name, instance.public_ip_address)

@click.command(name="fetch")
@click.pass_context
def dns_cmd_fetch(ctx):
    fail_on_debug(ctx)

    conf = ctx.obj["conf"]
    client = ctx.obj["client"]

    dns = iac.DNSManager(client.route53)
    record = dns.fetch_a_record(conf.host_name)
    console(record, to_dict=iac.ResourceRecord.to_dict)


@click.command(name="delete")
@click.pass_context
def dns_cmd_delete(ctx):
    fail_on_debug(ctx)

    conf = ctx.obj["conf"]
    client = ctx.obj["client"]

    instance = iac.fetch_instance(client.ec2, conf.instance_name)

    dns = iac.DNSManager(client.route53)
    dns.delete_a_record(conf.host_name, instance.public_ip_address)


iac_cmd.add_command(dns_cmd)
dns_cmd.add_command(dns_cmd_create)
dns_cmd.add_command(dns_cmd_fetch)
dns_cmd.add_command(dns_cmd_delete)
dns_cmd.add_command(x_dbgconf_cmd)
