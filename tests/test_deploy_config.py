"""Unit tests for core.deploy_config — runnable outside QGIS:

    python -m unittest discover -s tests

build_deploy_config() is exercised with an explicit `gispublisher_root`
(skipping get_gispublisher_root()'s own `npm root -g` subprocess call, exactly
like qgispublisher_dialog does once it has one cached), so none of this needs
npm/node installed. get_gispublisher_root() itself is exercised only via its
`npm_prefix`-given branch for the same reason — see
tests/test_dependencies_checker.py's own docstring for the same pure/adapter
split rationale.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import deploy_config  # noqa: E402


class GetGispublisherRootTests(unittest.TestCase):
    def test_windows_layout_from_prefix(self):
        with mock.patch.object(deploy_config.sys, "platform", "win32"):
            root = deploy_config.get_gispublisher_root(npm_prefix=r"C:\npm")
        # joined the way the code joins it: a literal backslash path only round-trips on Windows
        expected = deploy_config.pathlib.Path(r"C:\npm") / "node_modules" / "@lbdudc" / "gis-publisher"
        self.assertEqual(str(root), str(expected))

    def test_posix_layout_from_prefix(self):
        with mock.patch.object(deploy_config.sys, "platform", "linux"):
            root = deploy_config.get_gispublisher_root(npm_prefix="/usr/local")
        self.assertEqual(
            str(root), str(deploy_config.pathlib.Path("/usr/local/lib/node_modules/@lbdudc/gis-publisher"))
        )


class BuildDeployConfigTests(unittest.TestCase):
    def setUp(self):
        self._paths_to_clean = []

    def tearDown(self):
        for path in self._paths_to_clean:
            try:
                os.remove(path)
            except OSError:
                pass

    def _build(self, *args, **kwargs):
        kwargs.setdefault("gispublisher_root", "/opt/gispublisher")
        path = deploy_config.build_deploy_config(*args, **kwargs)
        self._paths_to_clean.append(path)
        with open(path, "r", encoding="utf-8") as f:
            return path, json.load(f)

    def test_local_defaults_host_when_not_given(self):
        _, data = self._build("local", {}, name="myapp", version="2.0.0")
        self.assertEqual(data["name"], "myapp")
        self.assertEqual(data["version"], "2.0.0")
        self.assertEqual(data["deploy"], {"type": "local"})
        self.assertEqual(data["host"], "http://localhost:80")

    def test_local_uses_given_host(self):
        _, data = self._build("local", {"host": "http://example.com"})
        self.assertEqual(data["host"], "http://example.com")

    def test_ssh_fields_mapped(self):
        fields = {
            "host": "1.2.3.4", "port": 2222, "username": "deploy",
            "cert_route": "/keys/id_rsa", "remote_repo_path": "/srv/app",
        }
        _, data = self._build("ssh", fields)
        self.assertEqual(
            data["deploy"],
            {
                "type": "ssh", "host": "1.2.3.4", "port": 2222, "username": "deploy",
                "certRoute": "/keys/id_rsa", "remoteRepoPath": "/srv/app",
            },
        )
        self.assertEqual(data["host"], "1.2.3.4")

    def test_ssh_domain_and_email_reach_the_config_only_when_given(self):
        fields = {
            "host": "1.2.3.4", "port": 22, "username": "deploy",
            "cert_route": "/keys/id_rsa", "remote_repo_path": "/srv/app",
        }
        _, plain = self._build("ssh", fields)
        self.assertNotIn("domain", plain["deploy"])
        self.assertNotIn("acmeEmail", plain["deploy"])

        _, https = self._build("ssh", {**fields, "domain": " gis.example.org ", "acme_email": "me@example.org"})
        self.assertEqual(https["deploy"]["domain"], "gis.example.org")
        self.assertEqual(https["deploy"]["acmeEmail"], "me@example.org")

        # an email without a domain means nothing: no HTTPS, no certificate
        _, only_email = self._build("ssh", {**fields, "acme_email": "me@example.org"})
        self.assertNotIn("acmeEmail", only_email["deploy"])

    def test_aws_domain_reaches_the_config(self):
        fields = {
            "region": "eu-west-1", "ami_id": "ami-1", "instance_type": "t3.micro", "instance_name": "n",
            "security_group": "sg-1", "key_name": "k", "username": "ubuntu", "ssh_key_path": "/k.pem",
            "remote_path": "/srv/app", "domain": "gis.example.org",
        }
        _, data = self._build("aws", fields)
        self.assertEqual(data["deploy"]["domain"], "gis.example.org")

    def test_generate_can_also_zip(self):
        _, plain = self._build("local", {}, name="a", version="1.0.0")
        self.assertNotIn("zip", plain)
        _, zipped = self._build("local", {}, name="a", version="1.0.0", zip_output=True)
        self.assertIs(zipped["zip"], True)
        self.assertEqual(zipped["deploy"], {"type": "local"})

    def test_aws_fields_mapped(self):
        fields = {
            "access_key": "AKIA...", "secret_key": "shh", "region": "eu-west-1",
            "ami_id": "ami-123", "instance_type": "t3.micro", "instance_name": "my-instance",
            "security_group": "sg-123", "key_name": "my-key", "username": "ec2-user",
            "ssh_key_path": "/keys/aws.pem", "remote_path": "/srv/app",
        }
        _, data = self._build("aws", fields)
        self.assertEqual(
            data["deploy"],
            {
                "type": "aws",
                "AWS_REGION": "eu-west-1",
                "AWS_AMI_ID": "ami-123",
                "AWS_INSTANCE_TYPE": "t3.micro",
                "AWS_INSTANCE_NAME": "my-instance",
                "AWS_SECURITY_GROUP_ID": "sg-123",
                "AWS_KEY_NAME": "my-key",
                "AWS_USERNAME": "ec2-user",
                "AWS_SSH_PRIVATE_KEY_PATH": "/keys/aws.pem",
                "REMOTE_REPO_PATH": "/srv/app",
            },
        )
        # No top-level "host" for AWS — nothing to default it to yet (the
        # instance doesn't exist until the deploy actually runs).
        self.assertNotIn("host", data)

    def test_aws_keys_never_reach_the_config_file(self):
        fields = {
            "access_key": "AKIASECRETKEY", "secret_key": "topsecretvalue", "region": "eu-west-1",  # pragma: allowlist secret
            "ami_id": "ami-123", "instance_type": "t3.micro", "instance_name": "my-instance",
            "security_group": "sg-123", "key_name": "my-key", "username": "ec2-user",
            "ssh_key_path": "/keys/aws.pem", "remote_path": "/srv/app",
        }
        path, _ = self._build("aws", fields)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("AKIASECRETKEY", text)
        self.assertNotIn("topsecretvalue", text)

    def test_overwrite_edited_layers_is_opt_in(self):
        _, data = self._build("local", {})
        self.assertNotIn("overwriteEditedLayers", data["deploy"])
        path, data = self._build("local", {}, overwrite_edited=True)
        self.assertTrue(data["deploy"]["overwriteEditedLayers"])

    def test_unknown_deploy_type_raises(self):
        with self.assertRaises(ValueError):
            deploy_config.build_deploy_config("carrier-pigeon", {}, gispublisher_root="/opt/gispublisher")

    def test_platform_paths_derived_from_gispublisher_root(self):
        _, data = self._build("local", {}, gispublisher_root="/opt/gispublisher")
        platform_dir = deploy_config.pathlib.Path("/opt/gispublisher") / "node_modules" / "@lbdudc" / "mini-lps" / "src" / "platform"
        self.assertEqual(data["platform"]["codePath"], str(platform_dir / "code"))
        self.assertEqual(data["platform"]["featureModel"], str(platform_dir / "model.xml"))
        self.assertEqual(data["platform"]["extraJS"], str(platform_dir / "extra.js"))

    def test_written_into_dest_dir_when_given(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path, _ = self._build("local", {}, dest_dir=tmpdir)
            self.assertEqual(os.path.dirname(path), tmpdir)

    @unittest.skipIf(sys.platform == "win32", "POSIX file permission bits don't apply on Windows")
    def test_file_permissions_restricted_to_owner_on_posix(self):
        aws_fields = {
            "access_key": "AKIAEXAMPLE", "secret_key": "shh", "region": "eu-west-1", "ami_id": "ami-1",
            "instance_type": "t3.micro", "instance_name": "app", "security_group": "sg-1", "key_name": "k",
            "username": "ubuntu", "ssh_key_path": "/k", "remote_path": "/home/ubuntu/app",
        }
        path, _ = self._build("aws", aws_fields)
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o600)


class DeployProblemTests(unittest.TestCase):
    def ssh(self, **overrides):
        fields = {"host": "203.0.113.5", "port": 22, "username": "u", "cert_route": "/k", "remote_repo_path": "/home/u/app"}
        fields.update(overrides)
        return fields

    def test_valid_ssh_and_local_have_no_problem(self):
        self.assertIsNone(deploy_config.deploy_problem("ssh", self.ssh()))
        self.assertIsNone(deploy_config.deploy_problem("local", {"host": "http://localhost:80"}))

    def test_remote_path_rules_match_the_uploader(self):
        for bad in ["", "/", "~", "~/app", "app", "/home", "/home/u/../..", "/a b/c", "/x/$(rm)", "/x/'y'"]:
            self.assertIsNotNone(deploy_config.deploy_problem("ssh", self.ssh(remote_repo_path=bad)), bad)
        for good in ["/home/u/app", "/opt/gis-app_1.0"]:
            self.assertIsNone(deploy_config.deploy_problem("ssh", self.ssh(remote_repo_path=good)), good)

    def test_host_must_not_be_a_url(self):
        for bad in ["http://1.2.3.4", "1.2.3.4/app", "my host"]:
            self.assertIn("not a URL", deploy_config.deploy_problem("ssh", self.ssh(host=bad)), bad)

    def test_domain_and_email_are_checked(self):
        for good in ["gis.example.org", "a-b.example.co.uk", "gp.localhost"]:
            self.assertIsNone(deploy_config.deploy_problem("ssh", self.ssh(domain=good)), good)
        self.assertIsNone(deploy_config.deploy_problem("ssh", self.ssh(domain="")))
        for bad in ["https://gis.example.org", "gis.example.org/app", "no_dots", "bad domain.org", "-x.example.org"]:
            self.assertIn("domain must be", deploy_config.deploy_problem("ssh", self.ssh(domain=bad)), bad)
        self.assertIn(
            "email",
            deploy_config.deploy_problem("ssh", self.ssh(domain="gis.example.org", acme_email="nope")),
        )
        self.assertIsNone(
            deploy_config.deploy_problem("ssh", self.ssh(domain="gis.example.org", acme_email="me@example.org"))
        )
        self.assertIsNotNone(deploy_config.deploy_problem("aws", {"remote_path": "/srv/app", "domain": "x y"}))

    def test_editing_over_plain_http_from_another_machine_is_flagged(self):
        warn = deploy_config.plain_http_editing_warning
        self.assertIn("plain HTTP", warn("ssh", self.ssh(), True))
        self.assertIn("plain HTTP", warn("aws", {}, True))
        self.assertIsNone(warn("ssh", self.ssh(), False))
        self.assertIsNone(warn("local", {}, True))
        self.assertIsNone(warn("ssh", self.ssh(domain="gis.example.org"), True))
        self.assertIn("plain HTTP", warn("ssh", self.ssh(domain="  "), True))

    def test_app_url(self):
        url = deploy_config.app_url
        self.assertEqual(url("ssh", {"host": "1.2.3.4"}), "http://1.2.3.4")
        self.assertEqual(url("ssh", {"host": "1.2.3.4", "domain": " gis.example.org "}), "https://gis.example.org")
        self.assertEqual(url("aws", {"domain": "gis.example.org"}), "https://gis.example.org")
        self.assertIsNone(url("aws", {}))
        self.assertIsNone(url("ssh", {}))
        self.assertEqual(url("local", {}), "http://localhost:80")
        self.assertEqual(url("local", {"host": "http://localhost:8080"}), "http://localhost:8080")
        self.assertIsNone(url("package", {"file": "/x.zip"}))

    def test_summary_says_what_will_happen_and_where_the_app_will_be(self):
        lines, warnings = deploy_config.deploy_summary(
            "ssh",
            {"host": "203.0.113.5", "username": "ubuntu", "remote_repo_path": "/home/ubuntu/app", "domain": "gis.example.org"},
        )
        text = " ".join(lines)
        self.assertIn("Deploys to ubuntu@203.0.113.5 over SSH, into /home/ubuntu/app.", text)
        self.assertIn("https://gis.example.org", text)
        self.assertIn("Point gis.example.org at 203.0.113.5", text)
        self.assertEqual(warnings, [])

    def test_summary_warns_about_plain_http_and_editing(self):
        _, warnings = deploy_config.deploy_summary("ssh", {"host": "1.2.3.4"})
        self.assertEqual(len(warnings), 1)
        self.assertIn("plain HTTP", warnings[0])
        _, warnings = deploy_config.deploy_summary("ssh", {"host": "1.2.3.4"}, has_editable_layers=True)
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("editing password" in w for w in warnings))
        # with a domain, or on this computer, nothing to warn about
        self.assertEqual(deploy_config.deploy_summary("ssh", {"host": "h", "domain": "gis.example.org"}, True)[1], [])
        self.assertEqual(deploy_config.deploy_summary("local", {}, True)[1], [])

    def test_summary_leaves_out_what_is_not_filled_in_yet(self):
        lines, _ = deploy_config.deploy_summary("ssh", {})
        self.assertEqual(lines[0], "Deploys to the server over SSH.")
        lines, _ = deploy_config.deploy_summary("aws", {})
        self.assertIn("Creates an EC2 instance and deploys to it.", lines[0])
        self.assertIn("once it exists", " ".join(lines))
        lines, _ = deploy_config.deploy_summary("aws", {"instance_type": "t3.medium", "region": "eu-west-1", "domain": "gis.example.org"})
        self.assertIn("(t3.medium, eu-west-1)", lines[0])
        self.assertIn("https://gis.example.org", " ".join(lines))

    def test_cli_command_for_an_ssh_deploy(self):
        command = deploy_config.cli_command(
            "ssh",
            {"host": "203.0.113.5", "port": 22, "username": "ubuntu", "cert_route": "C:\\keys\\my key.pem",
             "remote_repo_path": "/home/ubuntu/app", "domain": "gis.example.org", "acme_email": "me@example.org"},
            name="demo", version="2.0.0", folder="C:/data/layers",
        )
        self.assertEqual(
            command,
            'gispublisher C:/data/layers --name demo --app-version 2.0.0 --type ssh --host 203.0.113.5 '
            '--user ubuntu --key "C:\\keys\\my key.pem" --remote-path /home/ubuntu/app '
            '--domain gis.example.org --acme-email me@example.org',
        )

    def test_cli_command_leaves_out_defaults_and_secrets(self):
        command = deploy_config.cli_command(
            "aws",
            {"access_key": "AKIA", "secret_key": "shh", "region": "eu-west-1", "ami_id": "ami-1", "instance_type": "t3.micro",
             "instance_name": "n", "security_group": "sg-1", "key_name": "k", "username": "ubuntu",
             "ssh_key_path": "/k.pem", "remote_path": "/home/ubuntu/app", "domain": "", "acme_email": "x@y.zz"},
        )
        self.assertNotIn("AKIA", command)
        self.assertNotIn("shh", command)
        self.assertNotIn("--app-version", command)
        self.assertNotIn("--domain", command)
        self.assertNotIn("--acme-email", command, "an email means nothing without a domain")
        self.assertIn("--aws-region eu-west-1", command)
        self.assertIn("--key /k.pem", command)

    def test_cli_command_for_local(self):
        self.assertEqual(
            deploy_config.cli_command("local", {"host": "http://localhost:80"}, name="a"),
            'gispublisher "<folder with the layers>" --name a --type local --host http://localhost:80',
        )
        self.assertIn("--port 2222", deploy_config.cli_command("ssh", {"host": "h", "port": 2222}))
        self.assertNotIn("--port", deploy_config.cli_command("ssh", {"host": "h", "port": 22}))

    def test_aws_checks_its_own_remote_path_key(self):
        self.assertIsNotNone(deploy_config.deploy_problem("aws", {"remote_path": "/"}))
        self.assertIsNone(deploy_config.deploy_problem("aws", {"remote_path": "/home/ec2-user/code"}))


if __name__ == "__main__":
    unittest.main()
