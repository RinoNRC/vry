import os
import unittest
from unittest.mock import Mock, call, mock_open, patch

import requests

from src.requestsV import Requests


def response(status=200, payload=None, invalid_json=False):
    result = Mock(status_code=status, ok=200 <= status < 400)
    if invalid_json:
        result.json.side_effect = ValueError("private response body")
    else:
        result.json.return_value = payload
    return result


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.client = Requests.__new__(Requests)
        self.client.log = Mock()
        self.client.headers = {"Authorization": "test-only cached authorization"}
        self.client.lockfile = {"port": "12345", "password": "test-only-password"}
        self.client.puuid = "test-subject"
        self.client.pd_url = "https://pd.example.invalid"
        self.client.glz_url = "https://glz.example.invalid"
        self.client.get_current_version = Mock(return_value="test-version")
        self.request = self.start_patch("src.requestsV.requests.request", side_effect=AssertionError("Unmocked request"))
        self.get = self.start_patch("src.requestsV.requests.get", side_effect=AssertionError("Unmocked get"))
        self.sleep = self.start_patch("src.requestsV.time.sleep")

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def set_response(self, result):
        self.request.side_effect = None
        self.request.return_value = result

    def set_entitlements(self, result):
        self.get.side_effect = None
        self.get.return_value = result

    def test_remote_pd_returns_original_response_and_verifies_tls(self):
        result = response(payload={"Matches": []})
        self.set_response(result)
        self.assertIs(self.client.fetch("pd", "/matches", "get"), result)
        self.assertEqual(self.request.call_count, 1)
        self.assertTrue(self.request.call_args.kwargs["verify"])
        self.assertEqual(self.request.call_args.kwargs["timeout"], (3, 7))
        self.assertNotIn("json", self.request.call_args.kwargs)

    def test_json_body_is_forwarded_for_pd_put_and_on_retry(self):
        result = response(payload=[{"Subject": "test-subject"}])
        self.request.side_effect = [response(503, {}), result]
        body = ["test-subject"]
        self.assertIs(self.client.fetch("pd", "/name-service/v2/players", "put", json=body), result)
        for request_call in self.request.call_args_list:
            self.assertIs(request_call.kwargs["json"], body)

    def test_glz_and_custom_return_objects_or_none(self):
        for url_type in ("glz", "custom"):
            for payload in ({"value": 1}, [], "invalid scalar", None):
                with self.subTest(url_type=url_type, payload=payload):
                    self.set_response(response(payload=payload))
                    expected = payload if isinstance(payload, (dict, list)) else None
                    self.assertEqual(self.client.fetch(url_type, "https://example.invalid", "get"), expected)
                    self.assertTrue(self.request.call_args.kwargs["verify"])

    def test_invalid_json_preserves_pd_response_but_not_decoded_contracts(self):
        for url_type in ("pd", "glz", "custom"):
            for status in (200, 404):
                with self.subTest(url_type=url_type, status=status):
                    self.request.reset_mock()
                    result = response(status, invalid_json=True)
                    self.set_response(result)
                    value = self.client.fetch(url_type, "/endpoint", "get")
                    self.assertIs(value, result if url_type == "pd" else None)
                    self.assertEqual(self.request.call_count, 1)

    def test_permanent_remote_errors_never_retry_or_clear_headers(self):
        original = self.client.headers
        for url_type in ("pd", "glz", "custom"):
            for status in (403, 404):
                with self.subTest(url_type=url_type, status=status):
                    self.request.reset_mock()
                    self.set_response(response(status, {"errorCode": "BAD_CLAIMS"}))
                    self.client.fetch(url_type, "/endpoint", "get")
                    self.assertEqual(self.request.call_count, 1)
                    self.assertIs(self.client.headers, original)
        self.get.assert_not_called()
        self.sleep.assert_not_called()

    def test_transient_remote_errors_have_only_two_attempts(self):
        for status in (429, 500, 503):
            with self.subTest(status=status):
                self.request.reset_mock()
                self.sleep.reset_mock()
                result = response(status, {})
                self.set_response(result)
                self.assertIs(self.client.fetch("pd", "/endpoint", "get", rate_limit_seconds=100), result)
                self.assertEqual(self.request.call_count, 2)
                self.sleep.assert_called_once_with(5)

    def test_network_errors_are_bounded_and_do_not_leak_exception_text(self):
        for url_type in ("pd", "glz", "custom", "local"):
            with self.subTest(url_type=url_type):
                self.request.reset_mock()
                self.sleep.reset_mock()
                self.request.side_effect = requests.exceptions.Timeout("private credentials and body")
                self.assertIsNone(self.client.fetch(url_type, "/endpoint", "get"))
                expected = 3 if url_type == "local" else 2
                self.assertEqual(self.request.call_count, expected)
                self.assertEqual(self.sleep.call_count, expected - 1)
        self.assertNotIn("private", str(self.client.log.call_args_list))

    def test_401_and_bad_claims_refresh_once_without_erasing_cached_headers(self):
        for url_type in ("pd", "glz", "custom"):
            for status, payload in ((401, None), (400, {"errorCode": "BAD_CLAIMS"})):
                with self.subTest(url_type=url_type, status=status):
                    self.request.reset_mock()
                    self.request.side_effect = [response(status, payload), response(401, {})]
                    with patch.object(self.client, "get_headers", side_effect=[self.client.headers, {"Authorization": "refreshed test value"}]) as headers:
                        self.client.fetch(url_type, "/endpoint", "get")
                    self.assertEqual(headers.call_args_list, [call(), call(refresh=True)])
                    self.assertEqual(self.request.call_count, 2)
                    self.assertEqual(self.request.call_args.kwargs["headers"], {"Authorization": "refreshed test value"})
                    self.assertTrue(self.client.headers)

    def test_error_response_bodies_and_urls_are_not_logged_or_printed(self):
        result = response(500, invalid_json=True)
        result.text = "private response body with credentials"
        self.set_response(result)
        with patch("builtins.print") as output:
            self.assertIsNone(self.client.fetch("custom", "https://example.invalid/?private=credential", "get"))
        output.assert_not_called()
        self.assertNotIn("private", str(self.client.log.call_args_list))
        self.assertNotIn("credential", str(self.client.log.call_args_list))

    def test_missing_entitlement_prevents_remote_request(self):
        self.client.headers = {}
        self.set_entitlements(response(403, {}))
        self.assertIsNone(self.client.fetch("pd", "/endpoint", "get"))
        self.get.assert_called_once()
        self.request.assert_not_called()

    def test_refresh_failure_does_not_resend_stale_headers(self):
        original = self.client.headers
        result = response(401, {})
        self.set_response(result)
        with patch.object(self.client, "get_headers", side_effect=[original, None]):
            self.assertIs(self.client.fetch("pd", "/endpoint", "get"), result)
        self.assertEqual(self.request.call_count, 1)
        self.assertIs(self.client.headers, original)

    def test_local_parses_json_once_and_keeps_self_signed_tls_support(self):
        for payload in ({"ready": True}, []):
            with self.subTest(payload=payload):
                result = response(payload=payload)
                self.set_response(result)
                self.assertEqual(self.client.fetch("local", "/endpoint", "get"), payload)
                result.json.assert_called_once_with()
                self.assertFalse(self.request.call_args.kwargs["verify"])
                self.assertEqual(self.request.call_args.kwargs["timeout"], 5)

    def test_local_not_ready_retries_without_sleeping_after_last_attempt(self):
        for result in (response(payload={"errorCode": "RPC_ERROR"}), response(invalid_json=True), response(503, {})):
            with self.subTest(result=result):
                self.request.reset_mock()
                self.sleep.reset_mock()
                self.set_response(result)
                self.assertIsNone(self.client.fetch("local", "/endpoint", "get"))
                self.assertEqual(self.request.call_count, 3)
                self.assertEqual(self.sleep.call_count, 2)

    def test_local_permanent_errors_do_not_retry(self):
        for status in (401, 403, 404):
            with self.subTest(status=status):
                self.request.reset_mock()
                self.set_response(response(status, {}))
                self.assertIsNone(self.client.fetch("local", "/endpoint", "get"))
                self.assertEqual(self.request.call_count, 1)
        self.sleep.assert_not_called()

    def test_invalid_lockfile_values_never_send_requests(self):
        invalid = [None, [], {}, {"port": "12345"}]
        invalid += [{"port": port, "password": "test-only"} for port in (None, True, 1.2, 0, -1, 65536, "1/path", "\u00b2", "1" * 5000)]
        invalid += [{"port": "12345", "password": password} for password in (None, {}, [], 123, "", "bad:structure", "bad\nheader")]
        for lockfile in invalid:
            with self.subTest(lockfile=lockfile):
                self.client.lockfile = lockfile
                self.assertIsNone(self.client.fetch("local", "/endpoint", "get"))
                self.assertIsNone(self.client.get_headers(refresh=True))
                self.assertFalse(self.client.get_headers(init=True, refresh=True))
        self.request.assert_not_called()
        self.get.assert_not_called()

    def test_lockfile_parsing_uses_only_mocked_file(self):
        self.client.Error = Mock()
        self.client.Error.LockfileError.return_value = True
        valid = "test-client:1:12345:test-only-password:https\n"
        for contents, expected in ((valid, True), ("missing:parts", False), ("client:1:abc:test-only:https", False), ("client:1:12345:test:extra:https", False)):
            with self.subTest(contents=contents):
                with patch.dict(os.environ, {"LOCALAPPDATA": "mock-appdata"}), patch("builtins.open", mock_open(read_data=contents)):
                    parsed = self.client.get_lockfile()
                self.assertEqual(parsed is not None, expected)
        self.request.assert_not_called()
        self.get.assert_not_called()

    def test_cached_headers_need_no_entitlement_request(self):
        self.assertIs(self.client.get_headers(), self.client.headers)
        self.get.assert_not_called()

    def test_entitlement_failures_are_bounded_and_preserve_good_state(self):
        failures = [response(invalid_json=True), response(payload=[]), response(payload={}), response(500, {"subject": "bad", "accessToken": "bad", "token": "bad"}), response(payload={"subject": "test", "accessToken": "", "token": None}), response(payload={"subject": "test", "accessToken": "bad\nheader", "token": "test-entitlement"})]
        for result in failures:
            with self.subTest(result=result):
                self.get.reset_mock()
                self.sleep.reset_mock()
                self.set_entitlements(result)
                original = self.client.headers
                self.assertIsNone(self.client.get_headers(refresh=True))
                self.assertEqual(self.get.call_count, 3)
                self.assertEqual(self.sleep.call_count, 2)
                self.assertIs(self.client.headers, original)
                self.assertEqual(self.client.puuid, "test-subject")
        self.assertNotIn("private", str(self.client.log.call_args_list))

    def test_entitlement_network_failure_does_not_read_real_lockfile(self):
        self.get.side_effect = requests.exceptions.ConnectionError("private credentials")
        with patch.object(self.client, "get_lockfile") as lockfile:
            self.assertIsNone(self.client.get_headers(refresh=True))
        lockfile.assert_not_called()
        self.assertEqual(self.get.call_count, 3)
        self.assertNotIn("private", str(self.client.log.call_args_list))

    def test_entitlement_permanent_errors_fail_immediately(self):
        for result in (response(401, {}), response(403, {}), response(404, {}), response(payload={"message": "Invalid URI format"})):
            with self.subTest(result=result):
                self.get.reset_mock()
                self.set_entitlements(result)
                self.assertIsNone(self.client.get_headers(refresh=True))
                self.assertEqual(self.get.call_count, 1)
        self.sleep.assert_not_called()

    def test_init_not_ready_has_finite_startup_budget(self):
        self.client.headers = {}
        self.set_entitlements(response(payload={"message": "Entitlements token is not ready yet"}))
        self.assertIs(self.client.get_headers(init=True), False)
        self.assertEqual(self.get.call_count, 30)
        self.assertEqual(self.sleep.call_count, 29)

    def test_successful_entitlement_refresh_commits_complete_headers(self):
        self.get.side_effect = [response(invalid_json=True), response(payload={"subject": "new-test-subject", "accessToken": "test-access", "token": "test-entitlement"})]
        headers = self.client.get_headers(refresh=True)
        self.assertIs(headers, self.client.headers)
        self.assertEqual(headers["Authorization"], "Bearer test-access")
        self.assertEqual(headers["X-Riot-Entitlements-JWT"], "test-entitlement")
        self.assertEqual(self.client.puuid, "new-test-subject")
        self.assertEqual(self.get.call_count, 2)
        self.assertFalse(self.get.call_args.kwargs["verify"])
        self.assertEqual(self.get.call_args.kwargs["timeout"], 5)
        self.assertNotIn("test-access", str(self.client.log.call_args_list))
        self.assertNotIn("test-entitlement", str(self.client.log.call_args_list))

    def test_version_read_failure_does_not_replace_headers_or_subject(self):
        original = self.client.headers
        self.set_entitlements(response(payload={"subject": "new", "accessToken": "test-access", "token": "test-entitlement"}))
        self.client.get_current_version.side_effect = OSError("private path")
        self.assertIsNone(self.client.get_headers(refresh=True))
        self.assertIs(self.client.headers, original)
        self.assertEqual(self.client.puuid, "test-subject")

    def test_gui_skips_all_legacy_upstream_checks_and_updater(self):
        callback = Mock()
        with patch.dict(os.environ, {"VRY_GUI": "1"}), patch("builtins.input") as prompt, patch("src.requestsV.os.mkdir") as mkdir, patch("src.requestsV.subprocess.Popen") as popen:
            Requests.check_version("0", callback)
            Requests.check_status()
            Requests.copy_run_update_script("https://example.invalid/foreign.zip")
        self.get.assert_not_called()
        callback.assert_not_called()
        prompt.assert_not_called()
        mkdir.assert_not_called()
        popen.assert_not_called()

    def test_legacy_checks_use_timeouts(self):
        self.get.side_effect = requests.exceptions.Timeout("private")
        with patch.dict(os.environ, {"VRY_GUI": "0"}), patch("builtins.print"):
            Requests.check_version("0", Mock())
            Requests.check_status()
        self.assertEqual(self.get.call_count, 2)
        for request_call in self.get.call_args_list:
            self.assertEqual(request_call.kwargs["timeout"], (3, 10))

    def test_legacy_download_uses_timeout(self):
        self.get.side_effect = requests.exceptions.Timeout("test-only")
        with patch.dict(os.environ, {"VRY_GUI": "0", "APPDATA": "mock-appdata"}), patch("src.requestsV.os.mkdir"), patch("src.requestsV.shutil.copyfile"):
            with self.assertRaises(requests.exceptions.Timeout):
                Requests.copy_run_update_script("https://example.invalid/test.zip")
        self.assertEqual(self.get.call_args.kwargs["timeout"], (3, 30))

    def test_pbe_region_has_the_same_nested_structure_as_live(self):
        logs = "https://pd.pbe.a.pvp.net/account-xp/v1/test\nhttps://glz-na-1.na.a.pvp.net/test\n"
        with patch.dict(os.environ, {"LOCALAPPDATA": "mock-appdata"}), patch("builtins.open", mock_open(read_data=logs)):
            self.assertEqual(self.client.get_region(), ["na", ["na-1", "na"]])


if __name__ == "__main__":
    unittest.main()
