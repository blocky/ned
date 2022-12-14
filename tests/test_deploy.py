from unittest.mock import patch, Mock

import ned


@patch("fabric.Connection")
def test_remote_cmd_runner__from_instance_and_key_file(mock_fabric):
    dns_name = "dns-name"
    path = "path"
    username = "username"

    instance = ned.Instance(name="name", state="running", public_dns_name=dns_name)
    key_file = ned.KeyFile(path=path, username=username)

    ned.RemoteCMDRunner.from_instance_and_key_file(instance, key_file)

    mock_fabric.assert_called_once_with(
        host=dns_name,
        user=username,
        connect_kwargs={"key_filename": path},
    )


def test_remote_cmd_runner__copy():
    want = Mock()
    conn = Mock()
    conn.put.return_value = want

    path = "path"
    got = ned.RemoteCMDRunner(conn).copy(path)

    assert want == got
    conn.put.assert_called_once_with(path)


def test_remote_cmd_runner__run():
    want = Mock()
    conn = Mock()
    conn.run.return_value = want

    cmd = "cmd"
    got = ned.RemoteCMDRunner(conn).run(cmd)

    assert want == got
    conn.run.assert_called_once_with(cmd, hide=True)
