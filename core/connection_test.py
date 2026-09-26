"""Best-effort SSH/AWS deploy credential checks, run before the user commits
to a multi-minute Deploy only to find out a host is unreachable or a
credential is wrong.

Shells out to whatever client is already on PATH (`ssh`, `aws`) rather than
bundling a Python SSH/AWS SDK as a hard plugin dependency — same "shell out,
degrade gracefully if missing" philosophy as dependencies_checker.py's
find_node/find_npm. Neither check is a substitute for the real deploy: it's
a fast, best-effort sanity check, not a guarantee.
"""

import os
import shutil
import socket
import subprocess
import sys

from .dependencies_checker import find_ssh

_TCP_TIMEOUT_SECONDS = 6
_SSH_TIMEOUT_SECONDS = 12
_AWS_TIMEOUT_SECONDS = 15


def _subprocess_kwargs():
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def test_ssh_connection(host, port, username, cert_path):
    """Check an SSH deploy target is reachable and (best-effort) that
    `username`/`cert_path` would actually authenticate. Returns (ok, message).

    Always checks TCP reachability first, since that alone rules out the most
    common mistake (wrong host/port/firewall). If an `ssh` client binary is on
    PATH, also attempts a real (non-interactive) auth handshake — without one,
    this can only confirm the host:port is reachable, not that the given
    username/key would be accepted, and the message says which of the two it
    actually checked.
    """
    try:
        with socket.create_connection((host, int(port)), timeout=_TCP_TIMEOUT_SECONDS):
            pass
    except (OSError, ValueError) as e:
        return False, f"Could not reach {host}:{port} — {e}"

    ssh_bin = find_ssh()
    if not ssh_bin:
        return True, (
            f"{host}:{port} is reachable, but no local `ssh` client was found on PATH "
            "to verify the username/key too — install one (e.g. OpenSSH) to test "
            "authentication as well."
        )

    try:
        result = subprocess.run(  # nosec B603 - ssh_bin resolved via shutil.which()
            [
                ssh_bin,
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", f"ConnectTimeout={_TCP_TIMEOUT_SECONDS}",
                "-i", cert_path,
                "-p", str(port),
                f"{username}@{host}",
                "exit",
            ],
            capture_output=True, text=True, timeout=_SSH_TIMEOUT_SECONDS, **_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return False, f"Reachable, but the ssh handshake to {username}@{host}:{port} timed out."

    if result.returncode == 0:
        return True, f"Connected and authenticated to {username}@{host}:{port}."
    detail_lines = (result.stderr or result.stdout or "").strip().splitlines()
    detail = detail_lines[-1] if detail_lines else f"ssh exited with code {result.returncode}"
    return False, f"Reachable, but authentication failed: {detail}"


def test_aws_credentials(access_key, secret_key, region, profile=None):
    """Check AWS deploy credentials via `aws sts get-caller-identity` (with `profile`, the
    named AWS profile instead of the keys).
    Returns (ok, message) — returns (True, ...) with a caveat rather than
    (False, ...) when the `aws` CLI itself isn't installed, since that's not
    a credential problem and shouldn't read as one.
    """
    aws_bin = shutil.which("aws") or shutil.which("aws.cmd")
    if not aws_bin:
        return True, "AWS CLI not found on PATH — install it to enable credential testing before deploying."

    env = os.environ.copy()
    if profile:
        env["AWS_PROFILE"] = profile
    else:
        env["AWS_ACCESS_KEY_ID"] = access_key
        env["AWS_SECRET_ACCESS_KEY"] = secret_key
    env["AWS_DEFAULT_REGION"] = region or "us-east-1"

    try:
        result = subprocess.run(  # nosec B603 - aws_bin resolved via shutil.which()
            [aws_bin, "sts", "get-caller-identity", "--output", "text"],
            capture_output=True, text=True, timeout=_AWS_TIMEOUT_SECONDS, env=env, **_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return False, "AWS CLI timed out — check network access to AWS."

    if result.returncode == 0:
        return True, f"Credentials valid: {result.stdout.strip()}"
    detail_lines = (result.stderr or result.stdout or "").strip().splitlines()
    detail = detail_lines[-1] if detail_lines else f"aws exited with code {result.returncode}"
    return False, f"Credential check failed: {detail}"
