"""Unit tests for core.credentials (pure, runnable outside QGIS)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import credentials  # noqa: E402

KEY = "AKIAEXAMPLE"
SECRET = "wJalrXUtnFEMI"  # pragma: allowlist secret


class AwsProfileNamesTests(unittest.TestCase):
    def _files(self, config="", creds=""):
        directory = tempfile.mkdtemp()
        config_path = os.path.join(directory, "config")
        creds_path = os.path.join(directory, "credentials")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config)
        with open(creds_path, "w", encoding="utf-8") as f:
            f.write(creds)
        return config_path, creds_path

    def test_profiles_from_both_files_sorted_and_deduplicated(self):
        config, creds = self._files(
            "[default]\nregion = eu-west-1\n\n[profile work]\nregion = us-east-1\n\n[sso-session x]\nsso_start_url = u\n",
            "[default]\naws_access_key_id = A\n\n[Personal]\naws_access_key_id = B\n",
        )
        self.assertEqual(
            credentials.aws_profile_names(config, creds), ["Personal", "default", "work"]
        )

    def test_missing_files_give_no_profiles(self):
        self.assertEqual(credentials.aws_profile_names("/no/such/config", "/no/such/credentials"), [])


class DeployEnvironmentTests(unittest.TestCase):
    def test_keys_go_to_the_environment(self):
        env = credentials.deploy_environment("aws", {"access_key": f" {KEY} ", "secret_key": SECRET})
        self.assertEqual(env, {"AWS_ACCESS_KEY_ID": KEY, "AWS_SECRET_ACCESS_KEY": SECRET})

    def test_a_profile_replaces_the_keys(self):
        env = credentials.deploy_environment(
            "aws", {"auth_mode": "profile", "profile": "work", "access_key": KEY, "secret_key": SECRET}
        )
        self.assertEqual(env, {"AWS_PROFILE": "work"})

    def test_half_a_key_pair_and_other_targets_give_nothing(self):
        self.assertEqual(credentials.deploy_environment("aws", {"access_key": KEY}), {})
        self.assertEqual(credentials.deploy_environment("aws", {"auth_mode": "profile", "profile": " "}), {})
        for deploy_type in ("ssh", "local"):
            self.assertEqual(credentials.deploy_environment(deploy_type, {"access_key": KEY, "secret_key": SECRET}), {})


class MissingCredentialsTests(unittest.TestCase):
    def test_keys_mode(self):
        self.assertEqual(credentials.missing_aws_credentials({}), ["Access key", "Secret key"])
        self.assertEqual(credentials.missing_aws_credentials({"access_key": KEY}), ["Secret key"])
        self.assertEqual(credentials.missing_aws_credentials({"access_key": KEY, "secret_key": SECRET}), [])

    def test_saved_keys_count_as_present(self):
        self.assertEqual(credentials.missing_aws_credentials({}, saved_available=True), [])

    def test_profile_mode(self):
        self.assertEqual(credentials.missing_aws_credentials({"auth_mode": "profile"}), ["AWS profile"])
        self.assertEqual(credentials.missing_aws_credentials({"auth_mode": "profile", "profile": "work"}), [])


class _FakeSettings:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)


class _FakeConfig:
    def __init__(self, method=""):
        self.method = method
        self._id = ""
        self._name = ""
        self._map = {}

    def setName(self, name):
        self._name = name

    def setConfig(self, key, value):
        self._map[key] = value

    def config(self, key):
        return self._map.get(key, "")

    def setId(self, value):
        self._id = value

    def id(self):
        return self._id


class _FakeAuthManager:
    def __init__(self, locked=False, unlock_works=True):
        self.stored = {}
        self.locked = locked
        self.unlock_works = unlock_works
        self.unlock_calls = 0

    def masterPasswordIsSet(self):
        return not self.locked

    def setMasterPassword(self, verify):
        self.unlock_calls += 1
        if self.unlock_works:
            self.locked = False
        return self.unlock_works

    def storeAuthenticationConfig(self, config):
        config.setId(f"cfg{len(self.stored) + 1}")
        self.stored[config.id()] = dict(config._map)
        return True, config

    def updateAuthenticationConfig(self, config):
        if config.id() not in self.stored:
            return False
        self.stored[config.id()] = dict(config._map)
        return True

    def loadAuthenticationConfig(self, config_id, config, full):
        if config_id not in self.stored:
            return False, config
        for key, value in self.stored[config_id].items():
            config.setConfig(key, value)
        return True, config

    def removeAuthenticationConfig(self, config_id):
        return self.stored.pop(config_id, None) is not None


class AwsKeyStoreTests(unittest.TestCase):
    def _store(self, **kwargs):
        auth = _FakeAuthManager(**kwargs)
        settings = _FakeSettings()
        return credentials.AwsKeyStore(auth, settings, _FakeConfig), auth, settings

    def test_save_then_load_round_trip(self):
        store, auth, settings = self._store()
        self.assertFalse(store.has_saved())
        self.assertTrue(store.save(KEY, SECRET))
        self.assertTrue(store.has_saved())
        self.assertEqual(store.load(), (KEY, SECRET))
        # the setting holds only the id, never the keys
        self.assertNotIn(KEY, str(settings.values))
        self.assertNotIn(SECRET, str(settings.values))

    def test_saving_again_replaces_the_entry(self):
        store, auth, _ = self._store()
        store.save(KEY, SECRET)
        store.save("AKIANEW", "newsecret")  # pragma: allowlist secret
        self.assertEqual(len(auth.stored), 1)
        self.assertEqual(store.load(), ("AKIANEW", "newsecret"))  # pragma: allowlist secret

    def test_a_vanished_entry_is_stored_again(self):
        store, auth, _ = self._store()
        store.save(KEY, SECRET)
        auth.stored.clear()  # removed from the password manager by hand
        self.assertTrue(store.save(KEY, SECRET))
        self.assertEqual(store.load(), (KEY, SECRET))

    def test_forget_removes_the_entry_and_the_setting(self):
        store, auth, _ = self._store()
        store.save(KEY, SECRET)
        store.forget()
        self.assertEqual(auth.stored, {})
        self.assertFalse(store.has_saved())
        self.assertIsNone(store.load())

    def test_a_locked_manager_is_unlocked_first(self):
        store, auth, _ = self._store(locked=True)
        self.assertTrue(store.save(KEY, SECRET))
        self.assertEqual(auth.unlock_calls, 1)

    def test_a_manager_that_stays_locked_saves_and_loads_nothing(self):
        store, auth, _ = self._store(locked=True, unlock_works=False)
        self.assertFalse(store.save(KEY, SECRET))
        self.assertFalse(store.has_saved())
        self.assertIsNone(store.load())

    def test_nothing_saved_loads_nothing_without_prompting(self):
        store, auth, _ = self._store(locked=True)
        self.assertIsNone(store.load())
        self.assertEqual(auth.unlock_calls, 0)


if __name__ == "__main__":
    unittest.main()
