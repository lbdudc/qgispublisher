"""The cloud providers that rent a server over an API token (Hetzner Cloud, DigitalOcean).

Pure data and small checks, no Qt: the plugin's page for a provider is built from ``PROVIDERS``,
and ``core.deploy_config`` / ``core.credentials`` read the same names. Neither provider has been
tried against the real service (that needs an account with a payment method), only against a
fake API in code-uploader's tests.
"""

import json
import urllib.error
import urllib.request

PROVIDERS = {
    "hetzner": {
        "label": "Hetzner Cloud",
        "token_env": "HCLOUD_TOKEN",
        "token_help": "Hetzner Cloud console > your project > Security > API tokens (Read & Write).",
        "sizes": [
            ("cx22", "cx22 (2 vCPU, 4 GB)"),
            ("cx32", "cx32 (4 vCPU, 8 GB)"),
            ("cx42", "cx42 (8 vCPU, 16 GB)"),
        ],
        "regions": [
            ("fsn1", "Falkenstein (fsn1)"),
            ("nbg1", "Nuremberg (nbg1)"),
            ("hel1", "Helsinki (hel1)"),
            ("ash", "Ashburn (ash)"),
            ("hil", "Hillsboro (hil)"),
            ("sin", "Singapore (sin)"),
        ],
        "test_url": "https://api.hetzner.cloud/v1/servers?per_page=1",
    },
    "digitalocean": {
        "label": "DigitalOcean",
        "token_env": "DIGITALOCEAN_TOKEN",
        "token_help": "DigitalOcean control panel > API > Tokens > Generate New Token (Read and Write).",
        "sizes": [
            ("s-2vcpu-4gb", "s-2vcpu-4gb (2 vCPU, 4 GB)"),
            ("s-4vcpu-8gb", "s-4vcpu-8gb (4 vCPU, 8 GB)"),
            ("s-8vcpu-16gb", "s-8vcpu-16gb (8 vCPU, 16 GB)"),
        ],
        "regions": [
            ("fra1", "Frankfurt (fra1)"),
            ("ams3", "Amsterdam (ams3)"),
            ("lon1", "London (lon1)"),
            ("nyc3", "New York (nyc3)"),
            ("sfo3", "San Francisco (sfo3)"),
            ("sgp1", "Singapore (sgp1)"),
            ("tor1", "Toronto (tor1)"),
            ("blr1", "Bangalore (blr1)"),
        ],
        "test_url": "https://api.digitalocean.com/v2/account",
    },
}

CLOUD_TYPES = tuple(PROVIDERS)

# What a fresh machine of these providers has: root, and a folder the deploy may empty
DEFAULT_REMOTE_PATH = "/root/gispublisher-app"


def is_cloud(deploy_type):
    return deploy_type in PROVIDERS


def label(deploy_type):
    return PROVIDERS[deploy_type]["label"]


def token_env(deploy_type):
    return PROVIDERS[deploy_type]["token_env"]


def environment(deploy_type, fields):
    """The environment variable the CLI reads the provider's token from (``{}`` when empty)."""
    token = (fields.get("token") or "").strip()
    return {token_env(deploy_type): token} if token else {}


def check_token(deploy_type, token, timeout=10, opener=urllib.request.urlopen):
    """Asks the provider's API something harmless with the token: ``(ok, message)``."""
    token = (token or "").strip()
    if not token:
        return False, "Enter the API token first."
    request = urllib.request.Request(
        PROVIDERS[deploy_type]["test_url"], headers={"Authorization": f"Bearer {token}"}
    )
    name = label(deploy_type)
    try:
        with opener(request, timeout=timeout) as response:  # nosec B310 - a fixed https address
            json.loads(response.read().decode("utf-8") or "{}")
        return True, f"{name} accepted the token."
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return False, f"{name} refused the token: check that it is valid and has write access."
        return False, f"{name} answered {error.code}."
    except (urllib.error.URLError, OSError, ValueError) as error:
        return False, f"Could not reach {name}: {getattr(error, 'reason', error)}"
