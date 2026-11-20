"""Protect the native Telegram gateway from direct DoH/proxy bypasses.

Extract the real async method from source and supply offline transport stubs;
no Telegram credentials, external DNS, sockets or services are used.
"""
import ast
import asyncio
import logging
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[4] / "plugins/platforms/telegram/adapter.py"


def fixture(*, proxy=None, resolution_error=None, fallback=None):
    parsed = ast.parse(SOURCE.read_text(encoding="utf-8"))
    method = next(n for n in ast.walk(parsed) if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "_build_ptb_requests")
    cls = ast.ClassDef(name="StubAdapter", bases=[], keywords=[], body=[method],
                       decorator_list=[], type_params=[])
    tree = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(tree)
    resolver = Mock(return_value=proxy, side_effect=resolution_error)
    discover = Mock(return_value=object())
    builder = Mock(return_value=(object(), object()))
    env = {
        "os": os,
        "logger": logging.getLogger("niph-gateway-test"),
        "HTTPXRequest": object,
        "platform_ssl_context": lambda: None,
        "telegram_verify": lambda extra, fallback: fallback,
        "discover_fallback_ips": discover,
        "_await_with_thread_deadline": Mock(),
        "resolve_proxy_url": resolver,
        "proxy_target_hosts": lambda *args: ["api.telegram.org"],
        "build_ptb_requests": builder,
        "SEED_FALLBACK_IPS": ["149.154.166.110"],
        "_redact_telegram_error_text": lambda *args: "redacted",
        "env_proxy_for_redaction": lambda *args: None,
        "safe_proxy_url_for_log": lambda *args: "REDACTED",
    }
    exec(compile(tree, str(SOURCE), "exec"), env)
    instance = env["StubAdapter"]()
    instance.config = SimpleNamespace(extra={})
    instance.name = "telegram"
    instance._ptb_proxy_url = None
    instance._fallback_ips = Mock(return_value=[] if fallback is None else fallback)
    instance._env_float_clamped = Mock(return_value=1.0)
    instance._instrument_polling_request = lambda req: req
    return instance, resolver, discover, builder


class GatewayProtectedEgressTests(unittest.TestCase):
    def run_async(self, target):
        return asyncio.run(target._build_ptb_requests())

    def test_strict_requires_proxy_even_when_resolver_declines(self):
        target, resolver, discovery, builder = fixture(proxy=None)
        with patch.dict(os.environ, {"NIPH_NO_DIRECT_PATH": "1"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "requires an available proxy"):
                self.run_async(target)
        discovery.assert_not_called()
        target._fallback_ips.assert_not_called()
        builder.assert_not_called()

    def test_telegram_env_proxy_missing_fails_before_doh(self):
        target, _, discovery, builder = fixture(proxy=None)
        with patch.dict(os.environ,
                        {"TELEGRAM_PROXY": "http://127.0.0.1:9999"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "requires an available proxy"):
                self.run_async(target)
        discovery.assert_not_called()
        builder.assert_not_called()

    def test_inherited_https_proxy_prevents_doh(self):
        target, _, discovery, builder = fixture(proxy=None)
        with patch.dict(os.environ,
                        {"HTTPS_PROXY": "http://127.0.0.1:9999"}, clear=True):
            with self.assertRaises(RuntimeError):
                self.run_async(target)
        discovery.assert_not_called()
        builder.assert_not_called()

    def test_proxy_is_forwarded_without_doh(self):
        proxy = "http://127.0.0.1:9999"
        target, _, discovery, builder = fixture(proxy=proxy)
        target.config.extra["proxy_url"] = proxy
        with patch.dict(os.environ, {}, clear=True):
            a, b = self.run_async(target)
        discovery.assert_not_called()
        self.assertEqual(proxy, builder.call_args.kwargs["proxy_url"])
        self.assertEqual([], builder.call_args.kwargs["fallback_ips"])

    def test_resolver_error_never_discovers_doh(self):
        target, _, discovery, builder = fixture(
            resolution_error=RuntimeError("proxy unavailable"))
        with patch.dict(os.environ, {"NIPH_NO_DIRECT_PATH": "1"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "proxy unavailable"):
                self.run_async(target)
        discovery.assert_not_called()
        builder.assert_not_called()

    def test_legacy_fallback_ips_still_used_outside_strict_mode(self):
        target, resolver, discovery, builder = fixture(
            proxy=None, fallback=["149.154.166.110"])
        with patch.dict(os.environ, {}, clear=True):
            self.run_async(target)
        self.assertEqual(["149.154.166.110"],
                         builder.call_args.kwargs["fallback_ips"])
        discovery.assert_not_called()


if __name__ == "__main__":
    unittest.main()
