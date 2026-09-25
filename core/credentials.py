"""AWS credentials for a deployment: where they can come from, how they reach the
CLI, and how they are remembered.

The keys are never written to the config file the CLI reads: they go to it as
environment variables (``deploy_environment``), so nothing secret is left on disk. They
can be remembered in QGIS's own password manager (``AwsKeyStore``), which encrypts them
with the user's master password, or replaced by a named AWS profile (``aws_profile_names``).

Everything but ``AwsKeyStore``'s default wiring is pure, and the store takes the auth
manager as an argument, so ``tests/test_credentials.py`` covers it with a fake.
"""

import configparser
import os

AUTH_MODE_KEYS = "keys"
AUTH_MODE_PROFILE = "profile"

# The credentials setting: the id of the QGIS authentication configuration holding the keys
AUTHCFG_SETTING = "GISPublisher/awsAuthCfg"
REMEMBER_SETTING = "GISPublisher/awsRemember"

_CONFIG_NAME = "GISPublisher AWS access keys"


def _read_ini(path):
    parser = configparser.RawConfigParser()
    parser.optionxform = str  # profile names are case sensitive
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return None
    return parser


def aws_profile_names(config_path=None, credentials_path=None):
    """The AWS profiles the user has set up, sorted: the sections of ``~/.aws/config``
    (written ``[profile name]``, or ``[default]``) and of ``~/.aws/credentials``. The
    files are the AWS CLI's own; ``AWS_CONFIG_FILE`` and ``AWS_SHARED_CREDENTIALS_FILE``
    move them."""
    home = os.path.expanduser("~")
    config_path = config_path or os.environ.get("AWS_CONFIG_FILE") or os.path.join(home, ".aws", "config")
    credentials_path = (
        credentials_path
        or os.environ.get("AWS_SHARED_CREDENTIALS_FILE")
        or os.path.join(home, ".aws", "credentials")
    )

    names = set()
    config = _read_ini(config_path)
    if config is not None:
        for section in config.sections():
            if section == "default":
                names.add("default")
            elif section.startswith("profile "):
                names.add(section[len("profile "):].strip())
    credentials = _read_ini(credentials_path)
    if credentials is not None:
        names.update(credentials.sections())
    return sorted(n for n in names if n)


def deploy_environment(deploy_type, fields):
    """The environment variables the CLI needs to sign in to the deploy target: the
    access keys, or the chosen profile. ``{}`` for anything that has no credentials."""
    if deploy_type != "aws":
        return {}
    if fields.get("auth_mode") == AUTH_MODE_PROFILE:
        profile = (fields.get("profile") or "").strip()
        return {"AWS_PROFILE": profile} if profile else {}
    env = {}
    access_key = (fields.get("access_key") or "").strip()
    secret_key = (fields.get("secret_key") or "").strip()
    if access_key and secret_key:
        env["AWS_ACCESS_KEY_ID"] = access_key
        env["AWS_SECRET_ACCESS_KEY"] = secret_key
    return env


def missing_aws_credentials(fields, saved_available=False):
    """Labels of the credential fields still to fill in for an AWS deploy (``saved_available``:
    the keys are in the password manager and will be loaded)."""
    if fields.get("auth_mode") == AUTH_MODE_PROFILE:
        return [] if (fields.get("profile") or "").strip() else ["AWS profile"]
    if saved_available:
        return []
    missing = []
    if not (fields.get("access_key") or "").strip():
        missing.append("Access key")
    if not (fields.get("secret_key") or "").strip():
        missing.append("Secret key")
    return missing


class AwsKeyStore:
    """The AWS access keys in QGIS's password manager (an authentication configuration of
    the Basic kind: user name = access key ID, password = secret key).

    ``settings`` is a ``QgsSettings``-like object (``value``/``setValue``/``remove``) that
    keeps only the id of the configuration; ``auth_manager`` is
    ``QgsApplication.authManager()`` and ``config_class`` ``QgsAuthMethodConfig``.
    """

    def __init__(self, auth_manager, settings, config_class):
        self._auth = auth_manager
        self._settings = settings
        self._config_class = config_class

    def _saved_id(self):
        value = self._settings.value(AUTHCFG_SETTING, "")
        return str(value or "")

    def has_saved(self):
        """Whether keys were saved (does not open the password manager)."""
        return bool(self._saved_id())

    def _unlock(self):
        """Asks for the master password when the password manager is locked."""
        if self._auth.masterPasswordIsSet():
            return True
        return bool(self._auth.setMasterPassword(True))

    def save(self, access_key, secret_key):
        """Stores the keys (replacing the saved ones). Returns False when the password
        manager could not be unlocked or refused the entry."""
        if not self._unlock():
            return False
        config = self._config_class("Basic")
        config.setName(_CONFIG_NAME)
        config.setConfig("username", access_key)
        config.setConfig("password", secret_key)
        existing = self._saved_id()
        if existing:
            config.setId(existing)
            if self._auth.updateAuthenticationConfig(config):
                return True
            config.setId("")
        stored = self._auth.storeAuthenticationConfig(config)
        ok = stored[0] if isinstance(stored, tuple) else bool(stored)
        if not ok:
            return False
        self._settings.setValue(AUTHCFG_SETTING, config.id())
        return True

    def load(self):
        """``(access_key, secret_key)`` from the password manager, or ``None`` when there are
        none, it stays locked, or the entry is gone."""
        config_id = self._saved_id()
        if not config_id or not self._unlock():
            return None
        config = self._config_class()
        loaded = self._auth.loadAuthenticationConfig(config_id, config, True)
        if not (loaded[0] if isinstance(loaded, tuple) else loaded):
            return None
        access_key, secret_key = config.config("username"), config.config("password")
        return (access_key, secret_key) if access_key and secret_key else None

    def forget(self):
        """Removes the saved keys from the password manager and the setting."""
        config_id = self._saved_id()
        if config_id and self._unlock():
            self._auth.removeAuthenticationConfig(config_id)
        self._settings.remove(AUTHCFG_SETTING)


def default_key_store():
    """The store wired to QGIS itself (imports QGIS here, so the rest stays pure)."""
    from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

    return AwsKeyStore(QgsApplication.authManager(), QgsSettings(), QgsAuthMethodConfig)
