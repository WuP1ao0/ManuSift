"""Tests for the R-2026-06-15
(Phase 1 + 3b) destructive-
command classifier.

Covers:

  * The 3-state
    classification
    (``safe``,
    ``needs_confirm``,
    ``block``) for the
    most common
    commands on both
    POSIX and
    PowerShell.
  * The pipeline splitter
    (``ls; rm -rf /`` is
    ``block`` because the
    most-severe sub-
    command wins).
  * The redirect
    detector (``> file``
    is
    ``needs_confirm``).
  * Variable expansion
    (``rm -rf $HOME``,
    ``rm -rf ~``,
    ``rm -rf $TMP/old.log``)
    is
    ``block``.
  * PowerShell:
    ``Remove-Item
    -Recurse -Force
    $env:USERPROFILE``,
    ``Format-Volume``,
    ``Stop-Computer``.
  * Defensive tolerance:
    empty string,
    non-string input,
    corrupt
    ``shlex`` parse.
  * The integration with
    ``BashTool``:
    ``rm -rf /`` returns
    ``error_kind=permission_denied``;
    a mutating command
    without
    ``MANUSIFT_ALLOW_NEEDS_CONFIRM``
    is also rejected.
  * The ``matched_rule``
    field is populated
    for matched rules
    (``rm-rf-root``,
    ``dd-of-block-device``,
    ``ps-remove-item-recursive-root``,
    etc.).

Pattern follows the
agent-infra-iteration-
engineer skill rule I.4:
pure helper + thin
wiring, both tested.
"""
from __future__ import annotations

import json
import os
from typing import Any

import pytest

from manusift.tools.safety import (
    STATE_BLOCK,
    STATE_NEEDS_CONFIRM,
    STATE_SAFE,
    classify_command,
)


# --------------------------------------------------------------------
# safe: read-only commands
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "ls",
        "ls -la",
        "cat /etc/hostname",
        "head -n 5 /etc/passwd",
        "tail -f /var/log/syslog",
        "echo hello",
        "echo 'hello world'",
        "printf '%s\\n' x",
        "pwd",
        "whoami",
        "hostname",
        "date",
        "uname -a",
        "wc -l /etc/hosts",
        "stat /etc/hostname",
        "file /etc/hostname",
        "which python",
        "grep -r 'TODO' .",
        "egrep 'pattern' file",
        "find . -name '*.py'",
        "diff a.txt b.txt",
        "sort file.txt",
        "git status",
        "git log --oneline",
        "git diff HEAD~1",
        "git show HEAD",
        "git branch",
        "git tag",
        "git remote -v",
        "git fetch origin",
        "git ls-files",
        "man bash",
        "python script.py",
        "python3 script.py",
        "node server.js",
        "ruby -e 'puts 1'",
        "ping 127.0.0.1 -n 5",
        "traceroute example.com",
        "nslookup example.com",
        "dig example.com",
        "host example.com",
        "exit 7",
        "basename /etc/hostname",
        "dirname /etc/hostname",
        "rev <<< hello",
        "sleep 5",
    ],
)
def test_posix_safe_commands(cmd: str) -> None:
    cls = classify_command(cmd, shell="posix")
    assert cls.state == STATE_SAFE, (
        f"expected safe; got {cls.state} "
        f"for {cmd!r}: {cls.reason}"
    )


@pytest.mark.parametrize(
    "cmd",
    [
        "Get-Process",
        "Get-Service",
        "Get-Date",
        "Get-Content C:/x.txt",
        "Get-ChildItem C:/",
        "Select-Object Name,Id",
        "Where-Object { $_.Id -gt 0 }",
        "Format-Table",
        "Test-Path C:/",
        "ls",
        "cat",
        "dir",
        "pwd",
        "echo hi",
    ],
)
def test_powershell_safe_commands(cmd: str) -> None:
    cls = classify_command(cmd, shell="powershell")
    assert cls.state == STATE_SAFE, (
        f"expected safe; got {cls.state} "
        f"for {cmd!r}: {cls.reason}"
    )


# --------------------------------------------------------------------
# needs_confirm: mutating commands
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "mkdir /tmp/foo",
        "mkdir -p /tmp/a/b",
        "rmdir /tmp/empty",
        "rm file.txt",
        "rm /tmp/old.log",
        "touch /tmp/x",
        "chmod 644 file",
        "chmod -R 755 /tmp/foo",
        "chown user file",
        "tar -czf out.tgz dir",
        "zip out.zip dir",
        "rsync -av src/ dst/",
        "apt install foo",
        "apt-get install foo",
        "yum install foo",
        "dnf install foo",
        "brew install foo",
        "pip install requests",
        "pip3 install openpyxl",
        "npm install express",
        "yarn add lodash",
        "cargo build",
        "go build",
        "git add file.txt",
        "git commit -m 'msg'",
        "git push origin main",
        "git pull origin main",
        "git merge feature",
        "git rebase main",
        "git checkout feature",
        "git stash",
        "ssh user@host",
        "scp file user@host:",
        "curl https://example.com",
        "wget https://example.com",
        "kill 1234",
        "killall python",
        "pkill -f python",
        "export PATH=/x:$PATH",
        "unset FOO",
        "source script.sh",
        "alias ll='ls -la'",
        "cd /tmp",
        "pushd /tmp",
        "popd",
        "history",
        "jobs",
    ],
)
def test_posix_needs_confirm_commands(cmd: str) -> None:
    cls = classify_command(cmd, shell="posix")
    assert cls.state == STATE_NEEDS_CONFIRM, (
        f"expected needs_confirm; got {cls.state} "
        f"for {cmd!r}: {cls.reason}"
    )


@pytest.mark.parametrize(
    "cmd",
    [
        "Set-Content C:/x.txt 'hi'",
        "Add-Content C:/x.txt 'hi'",
        "New-Item -Path C:/x.txt -ItemType File",
        "Copy-Item a.txt b.txt",
        "Move-Item a.txt b.txt",
        "Rename-Item a.txt b.txt",
        "Remove-Item a.txt",
        "Start-Service foo",
        "Stop-Service foo",
        "Restart-Service foo",
        "Invoke-WebRequest https://example.com",
        "Out-File -Path C:/x.txt",
    ],
)
def test_powershell_needs_confirm_commands(cmd: str) -> None:
    cls = classify_command(cmd, shell="powershell")
    assert cls.state == STATE_NEEDS_CONFIRM, (
        f"expected needs_confirm; got {cls.state} "
        f"for {cmd!r}: {cls.reason}"
    )


# --------------------------------------------------------------------
# block: catastrophic commands
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf $HOME",
        "rm -rf ${HOME}",
        "rm -rf $HOME/old",
        "rm -rf ${PWD}",
        "rm -rf $TMP/old.log",
        "rm -rf ${USER}/foo",
        "rm -rf *",
        "rm -Rf /",
        "rm -fr /",
        "rm -f -r /",
        "rm -r -f /",
        "dd if=/dev/zero of=/dev/sda bs=1M",
        "dd of=/dev/nvme0n1 if=/dev/zero",
        "dd of=/dev/sda1 bs=1M count=10",
        "dd of=/dev/xvda bs=1M",
        "chmod 777 /",
        "chmod -R 777 /home",
        "chmod a+rwx /",
        "chmod o+w /",
        "mkfs /dev/sda1",
        "mkfs.ext4 /dev/sda1",
        "mkfs.xfs /dev/nvme0n1",
        "shutdown now",
        "shutdown -h now",
        "reboot",
        "halt",
        "poweroff",
        "wipefs /dev/sda",
        "shred /dev/sda",
    ],
)
def test_posix_blocked_commands(cmd: str) -> None:
    cls = classify_command(cmd, shell="posix")
    assert cls.state == STATE_BLOCK, (
        f"expected block; got {cls.state} "
        f"for {cmd!r}: {cls.reason}"
    )
    # Blocked
    # commands
    # must
    # report
    # a
    # ``matched_rule``
    # so the
    # audit
    # log
    # can
    # show
    # which
    # rule
    # fired.
    assert cls.matched_rule is not None


@pytest.mark.parametrize(
    "cmd",
    [
        "Remove-Item -Recurse -Force $env:USERPROFILE",
        "Remove-Item -Force -Recurse $env:USERPROFILE",
        "Remove-Item -Recurse $env:HOMEDRIVE\\Windows",
        "Remove-Item -Recurse C:\\",
        "Remove-Item $HOME",
        "Format-Volume -DriveLetter C",
        "Clear-Disk -Number 0",
        "Initialize-Disk -Number 0",
        "Remove-Partition -DriveLetter C",
        "Stop-Computer -Force",
        "Restart-Computer -Force",
    ],
)
def test_powershell_blocked_commands(cmd: str) -> None:
    cls = classify_command(cmd, shell="powershell")
    assert cls.state == STATE_BLOCK, (
        f"expected block; got {cls.state} "
        f"for {cmd!r}: {cls.reason}"
    )
    assert cls.matched_rule is not None


# --------------------------------------------------------------------
# Pipeline splitting
# --------------------------------------------------------------------


def test_pipeline_most_severe_wins_block_over_safe():
    """``ls; rm -rf /`` is
    split into two sub-
    commands. The most-
    severe (``block``)
    wins.
    """
    cls = classify_command("ls; rm -rf /")
    assert cls.state == STATE_BLOCK
    assert cls.matched_rule == "rm-rf-root"


def test_pipeline_most_severe_wins_block_over_needs_confirm():
    """``mkdir /tmp/foo;
    rm -rf /`` is
    ``block`` (because
    the right-hand side
    is catastrophic).
    """
    cls = classify_command(
        "mkdir /tmp/foo; rm -rf /"
    )
    assert cls.state == STATE_BLOCK


def test_pipeline_safe_chain_stays_safe():
    """``ls && echo hi`` is
    safe (both sides are
    safe).
    """
    cls = classify_command("ls && echo hi")
    assert cls.state == STATE_SAFE


def test_pipeline_safe_then_mutating_is_needs_confirm():
    """``ls && mkdir
    /tmp/foo`` is
    ``needs_confirm``
    (the right-hand side
    is mutating).
    """
    cls = classify_command(
        "ls && mkdir /tmp/foo"
    )
    assert cls.state == STATE_NEEDS_CONFIRM


def test_pipeline_pipe_classifies_both_sides():
    """``cat /etc/passwd |
    grep root`` is
    ``safe`` (both sides
    are safe).
    """
    cls = classify_command(
        "cat /etc/passwd | grep root"
    )
    assert cls.state == STATE_SAFE


# --------------------------------------------------------------------
# Redirect detection
# --------------------------------------------------------------------


def test_redirect_to_file_is_needs_confirm():
    cls = classify_command("echo hi > foo.txt")
    assert cls.state == STATE_NEEDS_CONFIRM
    assert cls.matched_rule == "redirect-to-file"


def test_redirect_to_append_is_needs_confirm():
    cls = classify_command("echo hi >> foo.txt")
    assert cls.state == STATE_NEEDS_CONFIRM
    assert cls.matched_rule == "redirect-to-file"


def test_redirect_to_dev_null_is_safe():
    """``/dev/null`` is a
    standard null sink;
    not a real write.
    """
    cls = classify_command("echo hi > /dev/null")
    assert cls.state == STATE_SAFE


def test_redirect_to_dev_null_windows_is_safe():
    """On Windows,
    ``NUL`` is the null
    device.
    """
    cls = classify_command("echo hi > NUL")
    assert cls.state == STATE_SAFE


def test_redirect_with_safe_command_still_needs_confirm():
    """A redirect from a
    safe command is
    still a write --
    the redirect is the
    mutation.
    """
    cls = classify_command("cat /etc/hostname > /tmp/x")
    assert cls.state == STATE_NEEDS_CONFIRM


def test_redirect_stderr_to_file():
    cls = classify_command("command 2> errors.log")
    assert cls.state == STATE_NEEDS_CONFIRM


# --------------------------------------------------------------------
# Variable expansion
# --------------------------------------------------------------------


def test_rm_rf_home_env_var_is_block():
    cls = classify_command("rm -rf $HOME")
    assert cls.state == STATE_BLOCK


def test_rm_rf_pwd_env_var_is_block():
    cls = classify_command("rm -rf ${PWD}")
    assert cls.state == STATE_BLOCK


def test_rm_rf_tilde_is_block():
    cls = classify_command("rm -rf ~")
    assert cls.state == STATE_BLOCK


def test_rm_rf_tmp_old_log_is_block():
    """Even a
    non-root path
    under a
    env-var is
    treated as
    potentially
    catastrophic
    (the env
    var could
    resolve to
    /).
    """
    cls = classify_command("rm -rf $TMP/old.log")
    assert cls.state == STATE_BLOCK


def test_chmod_world_writable_root_is_block():
    cls = classify_command("chmod 777 /")
    assert cls.state == STATE_BLOCK


# --------------------------------------------------------------------
# Defensive tolerance
# --------------------------------------------------------------------


def test_empty_command_is_safe():
    cls = classify_command("")
    assert cls.state == STATE_SAFE
    assert "empty" in cls.reason.lower()


def test_whitespace_only_command_is_safe():
    cls = classify_command("   \t\n   ")
    assert cls.state == STATE_SAFE


def test_non_string_command_is_safe():
    """A corrupt input
    (e.g. a non-string)
    is defensively
    classified as safe
    with a reason.
    """
    cls = classify_command(None)  # type: ignore[arg-type]
    assert cls.state == STATE_SAFE
    cls = classify_command(123)  # type: ignore[arg-type]
    assert cls.state == STATE_SAFE


def test_unbalanced_quotes_classified_safely():
    """A ``shlex`` parse
    failure (unbalanced
    quotes) is
    classified as safe
    (the bash tool
    itself will fail
    on the unbalanced
    string).
    """
    cls = classify_command(
        "echo 'hello"
    )
    # The
    # exact
    # state
    # depends
    # on
    # whether
    # the
    # high-level
    # rules
    # still
    # match
    # the
    # first
    # token
    # ("echo"),
    # which
    # they
    # do.
    assert cls.state in (STATE_SAFE, STATE_NEEDS_CONFIRM)


def test_unknown_command_is_needs_confirm_by_default():
    """A command we don't
    recognise is
    ``needs_confirm`` (we
    do NOT whitelist
    ``safe`` by
    default).
    """
    cls = classify_command(
        "some_garbage_command --foo"
    )
    assert cls.state == STATE_NEEDS_CONFIRM
    assert (
        "unrecognised" in cls.reason.lower()
    )


# --------------------------------------------------------------------
# Unknown shell
# --------------------------------------------------------------------


def test_unknown_shell_falls_back_to_posix():
    """An unknown shell
    argument is treated
    as ``"posix"`` (most
    agents in this
    project use bash on
    POSIX systems and
    PowerShell on
    Windows; this
    covers both).
    """
    cls = classify_command(
        "rm -rf /", shell="junk"
    )
    assert cls.state == STATE_BLOCK


# --------------------------------------------------------------------
# BashTool integration
# --------------------------------------------------------------------


def test_bash_blocks_rm_rf_root():
    """``BashTool.execute``
    with ``rm -rf /``
    returns
    ``error_kind=permission_denied``
    with the new
    classifier's
    reason.
    """
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "rm -rf /"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "permission_denied"
    err = out["error"].lower()
    assert (
        "blocked" in err or "rm -rf" in err
    )
    # The
    # matched
    # rule
    # id
    # is
    # in
    # the
    # envelope
    # (a
    # new
    # field
    # added
    # by
    # the
    # classifier).
    assert out.get("rule", "").startswith("rm")


def test_bash_blocks_mkfs():
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "mkfs.ext4 /dev/sda1"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "permission_denied"


def test_bash_blocks_needs_confirm_by_default():
    """A
    ``needs_confirm``
    command is also
    blocked (the user
    must set
    ``MANUSIFT_ALLOW_NEEDS_CONFIRM=true``
    to enable mutating
    commands).
    """
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "mkdir /tmp/foo"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "permission_denied"
    err = out["error"].lower()
    assert (
        "mutating" in err
        or "manusift_allow_needs_confirm" in err
    )
    err = out.get("error", "").lower()
    if (
        out.get("error_kind") == "permission_denied"
        and "mutating" in err
    ):
        raise AssertionError(
            f"classifier blocked a "
            f"needs_confirm command "
            f"even though the env var "
            f"is set: {out}"
        )


def test_bash_allows_needs_confirm_with_env(
    tmp_path, monkeypatch
) -> None:
    """When
    ``MANUSIFT_ALLOW_NEEDS_CONFIRM=true``,
    a ``needs_confirm``
    command is allowed
    past the classifier
    (the bash tool then
    runs it as a real
    subprocess).

    R-2026-06-15 (Phase 2 + P2-3):
    ``tmp_path`` is not
    inside the configured
    ``workspace_dir``
    (which defaults to
    ``./data/jobs``), so
    the bash tool would
    reject the ``cwd`` as
    outside the workspace.
    We patch
    ``get_settings`` to
    return a settings
    object with
    ``workspace_dir =
    tmp_path`` so the test
    exercises the "cwd is
    inside the workspace"
    path.
    """
    from manusift.config import Settings
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext
    from unittest import mock

    monkeypatch.setenv(
        "MANUSIFT_ALLOW_NEEDS_CONFIRM", "true"
    )
    # Patch the workspace
    # so ``tmp_path`` is
    # inside it.
    ws_settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        workspace_dir=tmp_path,  # type: ignore[arg-type]
    )
    import manusift.config as config_module
    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: ws_settings,
    )
    tool = BashTool()
    ctx = ToolContext(trace_id="t")
    target = tmp_path / "newdir"
    with mock.patch(
        "manusift.tools.agent_tools.bash.subprocess.run",
        return_value=mock.Mock(
            returncode=0,
            stdout="",
            stderr="",
        ),
    ) as run:
        out_str = tool.execute(
            {
                "command": f"mkdir {target}",
                "cwd": str(tmp_path),
            },
            ctx,
        )
    # The classifier
    # did not block the
    # command (because
    # the env var is
    # set).  The
    # subprocess was
    # invoked.
    assert run.called
    out = json.loads(out_str)
    # The result envelope
    # does NOT carry
    # ``error_kind=permission_denied``
    # for the classifier
    # reason.
    err = out.get("error", "").lower()
    if (
        out.get("error_kind") == "permission_denied"
        and "mutating" in err
    ):
        raise AssertionError(
            f"classifier blocked a "
            f"needs_confirm command "
            f"even though the env var "
            f"is set: {out}"
        )


def test_bash_allows_safe_commands():
    """Safe commands
    (``ls`` / ``echo``)
    are not blocked by
    the classifier.
    """
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "echo hi"},
            ToolContext(trace_id="t"),
        )
    )
    # The
    # bash
    # tool
    # runs
    # the
    # command.
    # The
    # actual
    # ``ok``
    # depends
    # on
    # whether
    # the
    # test
    # machine
    # has
    # a
    # shell.
    # The
    # important
    # assertion
    # is
    # that
    # the
    # classifier
    # does
    # NOT
    # return
    # ``permission_denied``.
    if "error_kind" in out:
        assert (
            out["error_kind"] != "permission_denied"
        )


# --------------------------------------------------------------------
# matched_rule
# --------------------------------------------------------------------


def test_matched_rule_for_rm_rf_root():
    cls = classify_command("rm -rf /")
    assert cls.matched_rule == "rm-rf-root"


def test_matched_rule_for_dd_block_device():
    cls = classify_command(
        "dd if=/dev/zero of=/dev/sda bs=1M"
    )
    assert cls.matched_rule == "dd-of-block-device"


def test_matched_rule_for_powershell_remove_item():
    cls = classify_command(
        "Remove-Item -Recurse -Force $env:USERPROFILE",
        shell="powershell",
    )
    assert (
        cls.matched_rule
        == "ps-remove-item-recursive-root"
    )


def test_matched_rule_for_safe_command():
    """A safe command
    DOES have a
    ``matched_rule``
    (the id of the
    safe rule that
    fired; e.g.
    ``posix.safe`` /
    ``ps.safe``). The
    classifier is
    happy to report
    which rule fired
    for audit logs.
    """
    cls = classify_command("ls")
    assert cls.matched_rule == "posix.safe"
