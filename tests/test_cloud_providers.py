"""Unit tests for core.cloud_providers and the cloud-provider branches of core.deploy_config /
core.credentials (pure, runnable outside QGIS)."""

import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cloud_providers, credentials, deploy_config, deploy_errors, state_store  # noqa: E402

FIELDS = {
    "token": " tok ", "server_name": "gis", "size": "cx32", "region": "nbg1",
    "ssh_key_path": "/keys/id", "remote_path": "", "domain": "", "acme_email": "",
}


class ProvidersTests(unittest.TestCase):
    def test_both_providers_have_what_the_page_needs(self):
        self.assertEqual(cloud_providers.CLOUD_TYPES, ("hetzner", "digitalocean"))
        for deploy_type, meta in cloud_providers.PROVIDERS.items():
            self.assertTrue(meta["sizes"] and meta["regions"], deploy_type)
            self.assertTrue(cloud_providers.token_env(deploy_type).endswith("_TOKEN"))
        self.assertFalse(cloud_providers.is_cloud("aws"))

    def test_the_token_goes_to_the_cli_as_its_environment_variable(self):
        self.assertEqual(credentials.deploy_environment("hetzner", FIELDS), {"HCLOUD_TOKEN": "tok"})
        self.assertEqual(credentials.deploy_environment("digitalocean", FIELDS), {"DIGITALOCEAN_TOKEN": "tok"})
        self.assertEqual(credentials.deploy_environment("hetzner", {"token": " "}), {})

    def test_check_token_reads_the_answer_of_the_api(self):
        def answer(body=b"{}", error=None):
            def opener(request, timeout):
                if error:
                    raise error
                self.assertEqual(request.get_header("Authorization"), "Bearer tok")
                return io.BytesIO(body)

            return opener

        ok, message = cloud_providers.check_token("hetzner", "tok", opener=answer())
        self.assertTrue(ok)
        self.assertIn("Hetzner Cloud accepted", message)
        denied = urllib.error.HTTPError("u", 401, "no", {}, None)
        ok, message = cloud_providers.check_token("digitalocean", "tok", opener=answer(error=denied))
        self.assertFalse(ok)
        self.assertIn("refused the token", message)
        ok, message = cloud_providers.check_token("hetzner", "tok", opener=answer(error=urllib.error.URLError("offline")))
        self.assertFalse(ok)
        self.assertIn("Could not reach", message)
        self.assertEqual(cloud_providers.check_token("hetzner", " ")[0], False)


class ConfigTests(unittest.TestCase):
    def _config(self, deploy_type, fields):
        path = deploy_config.build_deploy_config(deploy_type, fields, gispublisher_root="/opt/gp")
        self.addCleanup(os.remove, path)
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_the_server_is_described_and_the_token_never_written(self):
        data = self._config("hetzner", FIELDS)
        self.assertEqual(
            data["deploy"],
            {
                "type": "hetzner", "serverName": "gis", "serverSize": "cx32", "serverRegion": "nbg1",
                "certRoute": "/keys/id", "username": "root", "remoteRepoPath": "/root/gispublisher-app",
            },
        )
        self.assertNotIn("tok", json.dumps(data))

    def test_domain_reaches_the_config(self):
        data = self._config("digitalocean", {**FIELDS, "domain": "gis.example.org", "acme_email": "a@b.co"})
        self.assertEqual((data["deploy"]["domain"], data["deploy"]["acmeEmail"]), ("gis.example.org", "a@b.co"))

    def test_problems_summary_and_command(self):
        self.assertIsNone(deploy_config.deploy_problem("hetzner", FIELDS))
        self.assertIn("domain", deploy_config.deploy_problem("hetzner", {**FIELDS, "domain": "http://x"}))
        lines, warnings = deploy_config.deploy_summary("hetzner", FIELDS)
        self.assertIn("Hetzner Cloud server called gis (cx32, nbg1)", lines[0])
        self.assertTrue(any("plain HTTP" in w for w in warnings))
        self.assertEqual(deploy_config.app_url("digitalocean", {"domain": "gis.example.org"}), "https://gis.example.org")
        command = deploy_config.cli_command("hetzner", FIELDS, name="app")
        self.assertIn("--type hetzner --server-name gis --server-size cx32 --server-region nbg1 --key /keys/id", command)
        self.assertNotIn("tok", command)

    def test_only_the_non_secret_fields_are_kept_in_history(self):
        kept = state_store._RESTORABLE_DEPLOY_FIELDS["hetzner"]
        self.assertIn("server_name", kept)
        self.assertNotIn("token", kept)
        self.assertNotIn("ssh_key_path", kept)


class ErrorExplanationTests(unittest.TestCase):
    def test_provider_failures_are_explained(self):
        refused = deploy_errors.explain("Hetzner Cloud refused the API token (401): check that it is valid and can write.")
        self.assertIn("did not accept the token", refused.title)
        api = deploy_errors.explain("DigitalOcean POST /droplets failed (422): size is not available")
        self.assertIn("size is not available (HTTP 422)", api.hint)
        key = deploy_errors.explain("The public ssh key /k.pub was not found. Hetzner Cloud needs it")
        self.assertIn(".pub", key.title + key.hint)


class TokenStoreTests(unittest.TestCase):
    def test_a_second_store_uses_its_own_setting(self):
        settings = mock.Mock()
        settings.value.return_value = ""
        store = credentials.AwsKeyStore(mock.Mock(), settings, mock.Mock(), setting="GISPublisher/hetznerAuthCfg", name="n")
        self.assertFalse(store.has_saved())
        settings.value.assert_called_with("GISPublisher/hetznerAuthCfg", "")


if __name__ == "__main__":
    unittest.main()
