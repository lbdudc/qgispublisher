"""Turns the raw failure of a Generate/Deploy run into something a person can act on.

Pure Python (no Qt). `explain()` pattern-matches the CLI's error message plus the
tail of its output; anything it doesn't recognise returns None and the UI falls
back to the last error line.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Explanation:
    title: str
    hint: str


_PORT_RE = re.compile(r"Bind for [^\s]*?:(\d{2,5}) failed|port (\d{2,5}) is already", re.IGNORECASE)
_SERVICE_RE = re.compile(r"Service\(s\) failed: ([^\n]+)")
_WAITING_RE = re.compile(r"Timed out waiting for services: ([^\n]+)")

# (regex, builder) in priority order — the first match wins
_RULES = []


def _rule(pattern, flags=re.IGNORECASE):
    compiled = re.compile(pattern, flags)

    def register(builder):
        _RULES.append((compiled, builder))
        return builder

    return register


@_rule(r"use Deploy, the app has to be regenerated")
def _update_needs_deploy(match, text):
    return Explanation(
        "The data can't be updated on its own",
        "The layers or their fields changed since the last deployment, so the app has to be "
        "regenerated: run Deploy again without 'Update data only'.",
    )


@_rule(r"has not been deployed from here yet|Nothing is deployed in")
def _update_nothing_deployed(match, text):
    return Explanation(
        "There is nothing to update yet",
        "Deploy the app first. 'Update data only' then reloads the data of that deployment.",
    )


@_rule(r"The app is not running|not running on the server")
def _update_app_down(match, text):
    return Explanation(
        "The app is not running",
        "Updating the data needs the app to be up. Start it (or run Deploy) and try again.",
    )


@_rule(r"Docker is not installed|Command not found: docker|'docker' is not recognized|docker: command not found")
def _docker_missing(match, text):
    return Explanation(
        "Docker is not installed",
        "Install Docker Desktop (or Docker Engine) and try again.",
    )


@_rule(
    r"Docker is not running|Cannot connect to the Docker daemon|error during connect|"
    r"dockerDesktopLinuxEngine|docker daemon is not running"
)
def _docker_stopped(match, text):
    return Explanation(
        "Docker is not running",
        "Start Docker Desktop (or the Docker service) and deploy again.",
    )


@_rule(r"port is already allocated|address already in use|Bind for .* failed")
def _port_in_use(match, text):
    port = _PORT_RE.search(text)
    number = (port.group(1) or port.group(2)) if port else ""
    where = f" {number}" if number else ""
    return Explanation(
        f"Port{where} is already in use",
        "Another program, or a previous deployment of a different app, is using it. "
        "Stop it and deploy again.",
    )


@_rule(r"Permission denied \(publickey|Authentication failed|no supported authentication methods")
def _ssh_auth(match, text):
    return Explanation(
        "SSH authentication failed",
        "Check the username and the private key file. The key must not need a passphrase "
        "unless it is loaded in an ssh-agent.",
    )


@_rule(r"Host key verification failed|REMOTE HOST IDENTIFICATION HAS CHANGED")
def _ssh_hostkey(match, text):
    return Explanation(
        "The server's SSH host key changed",
        "If you reinstalled the server, remove its old entry from your known_hosts file and retry.",
    )


@_rule(
    r"Could not connect via ssh|Could not resolve hostname|Connection timed out|Connection refused|"
    r"No route to host|Network is unreachable"
)
def _ssh_unreachable(match, text):
    return Explanation(
        "Could not reach the server",
        "Check the host and port, that the server is running, and that a firewall is not blocking SSH.",
    )


@_rule(r"Passwordless sudo is required")
def _sudo(match, text):
    return Explanation(
        "The server user needs passwordless sudo",
        "Docker has to be installed on the server once: allow this user to run sudo without a password "
        "(or install Docker yourself) and deploy again.",
    )


@_rule(r"remoteRepoPath")
def _remote_path(match, text):
    return Explanation(
        "Invalid remote folder",
        "Use an absolute folder on the server, e.g. /home/<user>/app. It is emptied on every deploy.",
    )


@_rule(r"no space left on device")
def _disk_full(match, text):
    return Explanation(
        "Out of disk space",
        "Free some space (on this computer for a local deploy, on the server otherwise) and try again.",
    )


@_rule(r"Service\(s\) failed:")
def _service_failed(match, text):
    names = _SERVICE_RE.search(text)
    which = names.group(1).strip() if names else "a service"
    return Explanation(
        f"{which} failed to start",
        "The application was built but a service did not come up. "
        "Open the details to see its last log lines.",
    )


@_rule(r"Timed out waiting for services")
def _services_timeout(match, text):
    names = _WAITING_RE.search(text)
    which = f" ({names.group(1).strip()})" if names else ""
    return Explanation(
        f"The application did not become ready in time{which}",
        "Small machines can be too slow to start every service. Open the details for the logs, "
        "or try a machine with more memory.",
    )


@_rule(r"no viable alternative at input|mismatched input|extraneous input|token recognition error")
def _dsl_error(match, text):
    return Explanation(
        "GISPublisher could not read the project's layers",
        "A layer, field or app name probably clashes with the generator's grammar "
        "(for example a layer named like a keyword such as point or polygon). Rename it and retry.",
    )


@_rule(r"Docker Compose is not (installed|available)")
def _compose_missing(match, text):
    return Explanation(
        "Docker Compose is missing",
        "Install the Docker Compose plugin (it comes with Docker Desktop) and try again.",
    )


@_rule(r"(Hetzner Cloud|DigitalOcean) refused the API token")
def _cloud_token_refused(match, text):
    return Explanation(
        f"{match.group(1)} did not accept the token",
        "Check that the API token is the one of the right project, that it has Read & Write access and that "
        "it was not deleted. The Test token button checks it without deploying.",
    )


@_rule(r"public ssh key .* was not found")
def _cloud_public_key_missing(match, text):
    return Explanation(
        "The public half of the ssh key is missing",
        "The provider needs the .pub file that goes with the private key (same folder, same name plus .pub). "
        "Create the pair with ssh-keygen, or choose another key.",
    )


@_rule(r"(Hetzner Cloud|DigitalOcean) (GET|POST) \S+ failed \((\d+)\): (.+)")
def _cloud_api_error(match, text):
    return Explanation(
        f"{match.group(1)} refused the request",
        f"{match.group(4).strip()} (HTTP {match.group(3)}). Usually the size, the region or the image name "
        "is not one that provider has (they can be typed over in the Server box), or the account is at its limit.",
    )


def explain(*texts):
    """An Explanation for the failure described by `texts` (the CLI's error
    message, the tail of its output...), or None when nothing matches."""
    text = "\n".join(t for t in texts if t)
    if not text:
        return None
    for pattern, builder in _RULES:
        match = pattern.search(text)
        if match:
            return builder(match, text)
    return None


def last_error_line(lines):
    """The most informative last line of a log: the final one mentioning an
    error, else the final non-empty one."""
    cleaned = [ln.strip() for ln in lines if ln and ln.strip() and not ln.strip().startswith("@@gp ")]
    for line in reversed(cleaned):
        if re.search(r"error|failed|denied|refused|not found|cannot|could not|timed out", line, re.IGNORECASE):
            return line
    return cleaned[-1] if cleaned else ""
