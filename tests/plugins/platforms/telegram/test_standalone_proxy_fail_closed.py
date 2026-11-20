"""Regression for the *actual* standalone Telegram bot factory.

Load only the source function AST, so transport failures can be simulated
without reaching the Telegram API or loading user credentials.
"""
import ast
import logging
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[4] / "plugins/platforms/telegram/standalone.py"


def fixture(*, proxy=None, resolve_error=None, build_error=None):
    source = ast.parse(SOURCE.read_text(encoding="utf-8"))
    fn = next(node for node in source.body if isinstance(node, ast.FunctionDef)
              and node.name == "_telegram_bot")
    module = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(module)
    bot = Mock(return_value=object())
    resolve = Mock(return_value=proxy, side_effect=resolve_error)
    build = Mock(return_value=(object(), object()), side_effect=build_error)
    telegram = ModuleType("telegram")
    telegram.Bot = bot
    request = ModuleType("telegram.request")
    request.HTTPXRequest = type("HTTPXRequest", (), {})
    base = ModuleType("gateway.platforms.base")
    base.describe_proxy_error = lambda *args: None
    base.resolve_proxy_url = resolve
    base.safe_proxy_url_for_log = lambda p: "REDACTED"
    network = ModuleType("plugins.platforms.telegram.telegram_network")
    network.bot_api_urls = lambda extras: {}
    network.build_ptb_requests = build
    network.proxy_target_hosts = lambda *a: ["api.telegram.org"]
    network.telegram_verify = lambda *a: True
    imports = {"telegram": telegram, "telegram.request": request,
               "gateway.platforms.base": base,
               "plugins.platforms.telegram.telegram_network": network}
    ns = {"os": os, "logger": logging.getLogger("niph-test"),
          "_sanitize_error_text": lambda error: "redacted error",
          "_telegram_fallback_ips": lambda extra: []}
    exec(compile(module, str(SOURCE), "exec"), ns)
    return ns["_telegram_bot"], imports, bot, resolve, build


class TelegramProtectedEgressTests(unittest.TestCase):
    def test_proxy_builder_error_must_not_downgrade(self):
        factory, imports, bot, _, _ = fixture(
            proxy="http://127.0.0.1:9999", build_error=RuntimeError("broken"))
        with patch.dict(sys.modules, imports), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "protected transport unavailable"):
                factory("unused", {"proxy_url": "http://127.0.0.1:9999"})
        bot.assert_not_called()

    def test_resolver_error_must_not_downgrade(self):
        factory, imports, bot, _, _ = fixture(resolve_error=RuntimeError("bad proxy"))
        with patch.dict(sys.modules, imports), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "protected transport unavailable"):
                factory("unused", {"proxy_url": "http://127.0.0.1:9999"})
        bot.assert_not_called()

    def test_strict_no_proxy_must_deny(self):
        factory, imports, bot, _, _ = fixture(proxy=None)
        with patch.dict(sys.modules, imports), patch.dict(
                os.environ, {"NIPH_NO_DIRECT_PATH": "1"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "protected transport unavailable"):
                factory("unused")
        bot.assert_not_called()

    def test_environment_telegram_proxy_must_deny(self):
        factory, imports, bot, _, _ = fixture(proxy=None)
        with patch.dict(sys.modules, imports), patch.dict(
                os.environ, {"TELEGRAM_PROXY": "http://127.0.0.1:9999"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "protected transport unavailable"):
                factory("unused")
        bot.assert_not_called()

    def test_https_proxy_environment_must_not_bypass(self):
        factory, imports, bot, _, _ = fixture(proxy=None)
        with patch.dict(sys.modules, imports), patch.dict(
                os.environ, {"HTTPS_PROXY": "http://127.0.0.1:9911"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "protected transport unavailable"):
                factory("unused")
        bot.assert_not_called()

    def test_all_proxy_environment_must_not_bypass(self):
        factory, imports, bot, _, _ = fixture(proxy=None)
        with patch.dict(sys.modules, imports), patch.dict(
                os.environ, {"all_proxy": "http://127.0.0.1:9911"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "protected transport unavailable"):
                factory("unused")
        bot.assert_not_called()

    def test_explicit_proxy_is_passed_to_request(self):
        proxy = "http://127.0.0.1:9999"
        factory, imports, bot, _, build = fixture(proxy=proxy)
        with patch.dict(sys.modules, imports), patch.dict(os.environ, {}, clear=True):
            factory("unused", {"proxy_url": proxy})
        self.assertEqual(proxy, build.call_args.kwargs["proxy_url"])
        self.assertIn("request", bot.call_args.kwargs)

    def test_legacy_unrestricted_fallback_only_without_policy(self):
        factory, imports, bot, _, _ = fixture(build_error=RuntimeError("broken"))
        with patch.dict(sys.modules, imports), patch.dict(os.environ, {}, clear=True):
            factory("unused")
        bot.assert_called_once()
        self.assertNotIn("request", bot.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
