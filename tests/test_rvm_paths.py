from coworker.remote.paths import RemotePathError, RemotePathStyle
from coworker.remote.tools import RemoteTarget


def test_posix_remote_paths_are_pure_and_scoped():
    style = RemotePathStyle("posix")
    assert style.normalize("/workspace/./src/../main.py") == "/workspace/main.py"
    assert style.join("/workspace", "src/main.py") == "/workspace/src/main.py"
    assert style.is_under("/workspace", "/workspace/src")
    assert not style.is_under("/workspace", "/workspace-other/src")
    try:
        style.join("/workspace", "../../etc")
    except RemotePathError:
        pass
    else:
        raise AssertionError("traversal should be rejected")


def test_windows_paths_use_case_insensitive_mixed_separators():
    style = RemotePathStyle("windows")
    assert style.normalize(r"C:\Work\src\..\main.py") == r"C:\Work\main.py"
    assert style.is_under(r"C:\Work", r"c:/work\src\file.py")
    assert not style.is_under(r"C:\Work", r"C:\Worker\file.py")
    assert style.relative(r"C:\Work", r"c:/WORK/src") == r"src"
    assert style.normalize(r"\\server\Share\folder\..\file") == r"\\server\Share\file"
    assert style.quote(r"C:\it's file") == r"'C:\it''s file'"


def test_remote_target_relative_uses_matching_secondary_root():
    class Client:
        host_label = "host"

    target = RemoteTarget(
        host=object(),
        client=Client(),
        style=RemotePathStyle(),
        workspace="/workspace",
        roots=[{"path": "/workspace", "writable": True}, {"path": "/shared", "writable": False}],
    )
    assert target.relative("/shared/lib/module.py") == "lib/module.py"
    assert target.relative("/other/file.py") == "/other/file.py"
