"""lifelike P0-2: fatal client errors must not exit silently."""

import json
import tempfile
import types
import unittest
from pathlib import Path

from tests.test_telethon_adapter import _load_telethon_adapter_module


class _Logs:
    def __init__(self):
        self.records = []

    def __getattr__(self, level):
        return lambda msg, *args, **kwargs: self.records.append((level, msg % args if args else msg))

    def count(self, level):
        return sum(1 for lv, _ in self.records if lv == level)


class LifelikeWatchdogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = _load_telethon_adapter_module()
        self.logs = _Logs()
        self.module.logger = self.logs
        self.tmp = tempfile.TemporaryDirectory()
        self.health_dir = Path(self.tmp.name) / "health"

    def tearDown(self):
        self.tmp.cleanup()

    def _adapter(self, failures, *, watchdog=True, limit=3):
        adapter = self.module.TelethonPlatformAdapter({"id": "userbot"}, {}, None)
        adapter.incoming_media_ttl_seconds = 0
        adapter.lifelike_adapter_watchdog = watchdog
        adapter.lifelike_fatal_retry_limit = limit
        adapter._health_dir = self.health_dir
        adapter.calls = 0
        adapter.delays = []
        failures = list(failures)

        async def run_once(client_kwargs):
            adapter.calls += 1
            if failures:
                raise failures.pop(0)
            adapter._set_health(self.module.HEALTH_STATE_OK, "connected")
            adapter._stop_requested = True

        async def noop(*args, **kwargs):
            return None

        async def sleep(delay):
            adapter.delays.append(delay)

        adapter._run_client_once = run_once
        adapter._disconnect_current_client = noop
        adapter._sleep_before_reconnect = sleep
        adapter._build_client_kwargs = lambda: {}
        return adapter

    def _status(self):
        return json.loads((self.health_dir / "userbot.json").read_text())

    async def test_auth_fatal_logs_error_writes_fatal_and_does_not_retry(self):
        adapter = self._adapter([RuntimeError("The current session_string is unauthorized.")])
        with self.assertRaises(RuntimeError):
            await adapter.run()
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(adapter.delays, [])
        self.assertEqual(self.logs.count("error"), 1)
        status = self._status()
        self.assertEqual(status["state"], "fatal")
        self.assertEqual(status["reason"], "RuntimeError")
        self.assertEqual(adapter.health_snapshot()["state"], "fatal")  # terminate() keeps fatal

    async def test_non_auth_fatal_retries_limited_times_then_gives_up(self):
        adapter = self._adapter([RuntimeError("x"), RuntimeError("y"), RuntimeError("z")], limit=2)
        with self.assertRaises(RuntimeError):
            await adapter.run()
        self.assertEqual(adapter.calls, 3)
        self.assertEqual(len(adapter.delays), 2)
        self.assertGreaterEqual(adapter.delays[0], self.module.FATAL_RETRY_BASE_DELAY_SECONDS)
        self.assertGreaterEqual(adapter.delays[1], self.module.FATAL_RETRY_BASE_DELAY_SECONDS * 2)
        self.assertEqual(self.logs.count("error"), 3)  # 2 retry notices + final give-up
        self.assertEqual(self._status()["state"], "fatal")

    async def test_non_auth_fatal_recovers_after_retry(self):
        adapter = self._adapter([RuntimeError("transient")])
        await adapter.run()
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(self.logs.count("error"), 1)
        self.assertEqual(self._status()["state"], "stopped")

    async def test_switch_off_matches_legacy_behavior(self):
        adapter = self._adapter([ValueError("x")], watchdog=False)
        with self.assertRaises(ValueError):
            await adapter.run()
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(adapter.delays, [])
        self.assertEqual(self.logs.count("error"), 0)
        self.assertFalse(self.health_dir.exists())

    async def test_limit_zero_disables_retry(self):
        adapter = self._adapter([RuntimeError("x")], limit=0)
        with self.assertRaises(RuntimeError):
            await adapter.run()
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(self.logs.count("error"), 1)

    def test_auth_error_classification(self):
        adapter = self._adapter([])
        self.assertTrue(adapter._is_auth_fatal_error(RuntimeError("Client is unauthorized")))
        self.assertTrue(adapter._is_auth_fatal_error(RuntimeError("auth_key invalid")))
        self.assertTrue(
            adapter._is_auth_fatal_error(RuntimeError("the current session is no longer authorized."))
        )
        self.assertFalse(adapter._is_auth_fatal_error(ValueError("Could not find the input entity")))
        adapter._stop_requested = True
        self.assertFalse(adapter._fatal_retry_allowed(RuntimeError("x"), 0))

    def test_never_retry_errors(self):
        """Review: ValueError / Flood* / *Banned never trigger fatal retries."""
        adapter = self._adapter([], limit=3)

        class FloodWaitError(Exception):
            pass

        class PhoneNumberBannedError(Exception):
            pass

        for exc in (ValueError("bad session"), FloodWaitError("420"), PhoneNumberBannedError("banned")):
            self.assertTrue(adapter._is_never_retry_error(exc))
            self.assertFalse(adapter._fatal_retry_allowed(exc, 0))
        self.assertTrue(adapter._fatal_retry_allowed(RuntimeError("x"), 0))

    async def test_value_error_is_not_retried_even_with_limit(self):
        adapter = self._adapter([ValueError("x")], limit=3)
        with self.assertRaises(ValueError):
            await adapter.run()
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(self._status()["state"], "fatal")

    def test_default_limit_is_zero_and_redact_on(self):
        adapter = self.module.TelethonPlatformAdapter({"id": "userbot"}, {}, None)
        self.assertEqual(getattr(adapter, "lifelike_fatal_retry_limit", 0), 0)
        self.assertTrue(getattr(adapter, "lifelike_log_redact", True))
        if hasattr(adapter, "lifelike_fatal_retry_limit"):
            del adapter.lifelike_fatal_retry_limit
        self.assertEqual(adapter.lifelike_fatal_retry_limit_value(), 0)

    def test_fatal_retry_delay_is_capped(self):
        delay = self.module.TelethonPlatformAdapter._compute_fatal_retry_delay
        self.assertEqual(delay(1), 30.0)
        self.assertEqual(delay(2), 60.0)
        self.assertEqual(delay(10), self.module.FATAL_RETRY_MAX_DELAY_SECONDS)

    async def test_inbound_timestamp_and_snapshot(self):
        adapter = self._adapter([])
        adapter._running = True
        adapter.log_processed_messages_only = True
        adapter._message_converter = types.SimpleNamespace(is_topic_service_message=lambda m: True)
        self.assertIsNone(adapter.health_snapshot()["last_inbound_at"])
        await adapter._on_new_message(types.SimpleNamespace(message=types.SimpleNamespace(out=True)))
        self.assertIsNone(adapter.health_snapshot()["last_inbound_at"])
        await adapter._on_new_message(types.SimpleNamespace(message=types.SimpleNamespace(out=False)))
        snap = adapter.health_snapshot()
        self.assertIsNotNone(snap["last_inbound_at"])
        self.assertEqual(snap["connected"], False)
        self.assertEqual(
            set(snap), {"state", "reason", "since", "last_inbound_at", "connected", "reconnect_attempt"}
        )

    def test_health_write_failure_is_swallowed(self):
        adapter = self._adapter([])
        blocker = Path(self.tmp.name) / "file"
        blocker.write_text("x")
        adapter._health_dir = blocker / "health"
        adapter._set_health(self.module.HEALTH_STATE_OK, "connected")
        self.assertEqual(self.logs.count("warning"), 1)

    def test_no_health_dir_without_astrbot_path(self):
        adapter = self._adapter([])
        adapter._health_dir = None
        self.module.get_astrbot_plugin_data_path = None
        self.assertIsNone(adapter._resolve_health_dir())
        adapter._set_health(self.module.HEALTH_STATE_OK, "connected")  # no crash, no file


if __name__ == "__main__":
    unittest.main()

    def test_commit_log_redacts_body_by_default(self):
        """Privacy review #4: INFO commit log carries text_len, not text=%r, unless switched off."""
        import inspect

        src = inspect.getsource(self.module.TelethonPlatformAdapter._on_new_message)
        self.assertIn('getattr(self, "lifelike_log_redact", True)', src)
        self.assertIn("text_len=%d", src)
