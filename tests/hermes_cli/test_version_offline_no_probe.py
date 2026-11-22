"""Local version diagnostics must not initiate passive network update probes.

The user explicitly requests network checks through `hermes update --check`.
Displaying version metadata, even from Termux/REPL paths, grants no egress.
"""
from types import SimpleNamespace
import sys

import pytest

from hermes_cli import _startup_fast


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_fast_version_never_calls_remote_update_probe(monkeypatch, capsys, flag):
    import hermes_cli.source_check as source_check

    def forbidden(*args, **kwargs):
        raise AssertionError("hermes --version tried an unapproved update probe")

    monkeypatch.setattr(source_check, "check_for_updates", forbidden)
    monkeypatch.setattr(_startup_fast, "container_mode_may_be_active", lambda: False)
    assert _startup_fast.try_fast_version([flag]) is True
    stdout = capsys.readouterr().out
    assert "Install directory:" in stdout
    assert "Python:" in stdout
    assert "Update available" not in stdout


def test_slow_version_command_disables_update_probes(monkeypatch):
    from hermes_cli import main

    calls = []
    monkeypatch.setattr(_startup_fast, "print_fast_version_info", lambda **kw: calls.append(kw))
    main.cmd_version(SimpleNamespace())
    assert calls == [{"check_updates": False}]


def test_termux_version_paths_remain_local(monkeypatch):
    from hermes_cli import main

    calls = []
    monkeypatch.setattr(main, "_is_termux_startup_environment", lambda: True)
    monkeypatch.setattr(main, "_wants_tui_early", lambda argv: False)
    monkeypatch.setattr(main, "_print_version_info", lambda **kw: calls.append(kw))
    for argv in (["hermes", "--version"], ["hermes", "-V"]):
        monkeypatch.setattr(sys, "argv", argv)
        assert main._try_termux_fast_cli_launch() is True
    assert calls == [{"check_updates": False}, {"check_updates": False}]


def test_repl_version_never_requests_update_status(monkeypatch):
    from hermes_cli import main, cli_loops_mixin

    calls = []
    monkeypatch.setattr(main, "_print_version_info", lambda **kw: calls.append(kw))
    for cls in vars(cli_loops_mixin).values():
        if isinstance(cls, type) and "_cmd_version" in cls.__dict__:
            cls._cmd_version(None, "/version")
            break
    else:
        pytest.fail("REPL /version command handler not found")
    assert calls == [{"check_updates": False}]


def test_explicit_update_status_is_not_deleted(monkeypatch, capsys):
    import hermes_cli.source_check as source_check

    calls = []
    monkeypatch.setattr(source_check, "check_for_updates", lambda **kw:
                        (calls.append(kw) or {"behind": 0}))
    _startup_fast.print_fast_version_info(check_updates=True)
    assert calls == [{"passive": True}]
    assert "Up to date" in capsys.readouterr().out
