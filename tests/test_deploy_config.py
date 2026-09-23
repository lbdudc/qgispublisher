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
        self.assertEqual(str(root), str(deploy_config.pathlib.Path(r"C:\npm\node_modules\@lbdudc\gis-publisher")))

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
                "AWS_ACCESS_KEY_ID": "AKIA...",
                "AWS_SECRET_ACCESS_KEY": "shh",
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
        path, _ = self._build("aws", {"secret_key": "shh"})
        mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
