import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

from . import cloud_providers
from .dependencies_checker import find_npm


def get_gispublisher_root(npm_prefix=None):
    """Return the install path of the @lbdudc/gis-publisher npm package.

    Pass `npm_prefix` (an already-resolved `npm config get prefix` value) to
    avoid spawning `npm root -g` — used by dependencies_checker.gather_requirements(),
    which already paid for one npm prefix lookup and derives this the same way
    npm itself would (`<prefix>/node_modules` on Windows, `<prefix>/lib/node_modules`
    elsewhere), so a caller that already has the prefix never needs a second
    npm subprocess just for this.
    """
    if npm_prefix is None:
        npm_path = find_npm()
        result = subprocess.run(  # nosec B603 - npm_path is a fully-resolved path from shutil.which()
            [npm_path, "root", "-g"],
            capture_output=True,
            text=True,
        )
        npm_root = pathlib.Path(result.stdout.strip())
    else:
        npm_root = pathlib.Path(npm_prefix) / ("node_modules" if sys.platform == "win32" else "lib/node_modules")
    return npm_root / "@lbdudc" / "gis-publisher"


_REMOTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._\-/]+$")


def remote_path_problem(remote_path):
    """Why `remote_path` can't be a deployment folder on a server, or None.

    Same rules as the code uploader (normalizeConfig/assertSafeRemotePath): the
    folder is emptied on every deploy, so it must be an absolute, plain path at
    least two levels deep — never "/", "~" or something with spaces or quotes.
    """
    remote_path = (remote_path or "").strip()
    if not _REMOTE_PATH_RE.match(remote_path):
        return (
            "The remote folder must be an absolute path made of letters, digits and . _ - / "
            "(for example /home/ubuntu/app)."
        )
    segments = [s for s in remote_path.split("/") if s]
    if len(segments) < 2 or ".." in segments:
        return (
            "The remote folder is too shallow or contains '..'. Use a folder like /home/ubuntu/app: "
            "it is emptied on every deploy."
        )
    return None


_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z0-9-]{2,63}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def domain_problem(domain, email=""):
    """Why the domain (and the certificate email) can't be used for HTTPS, or None.

    Empty is fine: the app is then served over plain HTTP at the server's address."""
    domain = (domain or "").strip()
    email = (email or "").strip()
    if not domain:
        return None
    if "://" in domain or "/" in domain or not _DOMAIN_RE.match(domain):
        return "The domain must be a name like gis.example.org, without http:// or a path."
    if email and not _EMAIL_RE.match(email):
        return "The email for the HTTPS certificate does not look like an email address."
    return None


def deploy_problem(deploy_type, fields):
    """The first problem with the deploy form's values that would make the run fail
    anyway (after minutes of building), as a sentence for the user; None when fine."""
    if deploy_type == "ssh":
        host, remote_path = fields.get("host", ""), fields.get("remote_repo_path")
    elif deploy_type == "aws":
        host, remote_path = "", fields.get("remote_path")
    elif cloud_providers.is_cloud(deploy_type):
        host, remote_path = "", fields.get("remote_path") or cloud_providers.DEFAULT_REMOTE_PATH
    else:
        return None

    if host and (re.search(r"[\s/]", host.strip()) or "://" in host):
        return "The host must be a name or IP address (for example 203.0.113.5), not a URL."
    return domain_problem(fields.get("domain"), fields.get("acme_email")) or remote_path_problem(remote_path)


def plain_http_editing_warning(deploy_type, fields, has_editable_layers):
    """A sentence to confirm with the user when the app lets people edit data but is served
    over plain HTTP from another machine (the editing password would cross the network
    unencrypted), else None. A local deployment is only reachable from this machine."""
    if not has_editable_layers or deploy_type == "local" or (fields.get("domain") or "").strip():
        return None
    return (
        "Some layers are editable, and without a domain the app is served over plain HTTP: the editing "
        "password would travel unencrypted.\n\nEnter a domain in the deploy settings to serve the app "
        "over HTTPS. Deploy anyway?"
    )


def app_url(deploy_type, fields):
    """Where the app will answer, when the form already says so, else None. A domain means
    HTTPS there; otherwise plain HTTP at the server's address."""
    domain = (fields.get("domain") or "").strip()
    if deploy_type in ("ssh", "aws", *cloud_providers.CLOUD_TYPES) and domain:
        return f"https://{domain}"
    if deploy_type == "ssh" and (fields.get("host") or "").strip():
        return f"http://{fields['host'].strip()}"
    if deploy_type == "local":
        return (fields.get("host") or "http://localhost:80").strip()
    return None


def deploy_summary(deploy_type, fields, has_editable_layers=False):
    """What the Deploy button will do, in plain sentences: ``(lines, warnings)``. Built from
    the form's values as they are, whatever is still empty is left out."""
    lines, warnings = [], []
    domain = (fields.get("domain") or "").strip()
    url = app_url(deploy_type, fields)

    if deploy_type == "local":
        lines.append("Runs the app on this computer with Docker.")
    elif deploy_type == "ssh":
        who = (fields.get("username") or "").strip()
        host = (fields.get("host") or "").strip()
        where = f"{who}@{host}" if who and host else host or "the server"
        folder = (fields.get("remote_repo_path") or "").strip()
        lines.append(f"Deploys to {where} over SSH" + (f", into {folder}." if folder else "."))
    elif deploy_type == "aws":
        kind = (fields.get("instance_type") or "").strip()
        region = (fields.get("region") or "").strip()
        detail = ", ".join(x for x in (kind, region) if x)
        lines.append("Creates an EC2 instance" + (f" ({detail})" if detail else "") + " and deploys to it.")
    elif cloud_providers.is_cloud(deploy_type):
        detail = ", ".join(x for x in ((fields.get("size") or "").strip(), (fields.get("region") or "").strip()) if x)
        name = (fields.get("server_name") or "").strip()
        lines.append(
            f"Creates a {cloud_providers.label(deploy_type)} server"
            + (f" called {name}" if name else "")
            + (f" ({detail})" if detail else "")
            + " on the first deploy and deploys to it; later deploys find it again by its name."
        )

    if url:
        lines.append(f"The app will be at {url}.")
    elif deploy_type == "aws" or cloud_providers.is_cloud(deploy_type):
        lines.append("The app will be at the server's address once it exists" + (f", and at https://{domain}." if domain else "."))
    if domain and deploy_type in ("ssh", "aws", *cloud_providers.CLOUD_TYPES):
        where = fields.get("host", "").strip() if deploy_type == "ssh" else "the new server"
        lines.append(f"Point {domain} at {where or 'the server'} and keep ports 80 and 443 open: the certificate is issued for it.")
    if plain_http_editing_warning(deploy_type, fields, has_editable_layers):
        warnings.append("Editable layers over plain HTTP: the editing password would travel unencrypted. Add a domain.")
    if deploy_type in ("ssh", "aws", *cloud_providers.CLOUD_TYPES) and not domain:
        warnings.append("Without a domain the app is served over plain HTTP.")
    return lines, warnings


def _quote(value):
    """A command line argument, quoted for a shell when it needs it."""
    text = str(value)
    if text and all(c.isalnum() or c in "._-/:@=+," for c in text):
        return text
    return '"' + text.replace('"', '\\"') + '"'


def cli_command(deploy_type, fields, name="app", version="1.0.0", folder="<folder with the layers>"):
    """The `gispublisher` command line that does what the deploy form does, as text. Secrets
    (AWS keys, a cloud API token) are left out: the CLI takes them from the environment. `folder` is the
    shapefile folder to publish."""
    parts = ["gispublisher", _quote(folder), "--name", _quote(name)]
    if version and version != "1.0.0":
        parts += ["--app-version", _quote(version)]

    def add(flag, value):
        if value is not None and str(value).strip() != "":
            parts.extend([flag, _quote(str(value).strip())])

    parts += ["--type", deploy_type]
    if deploy_type == "local":
        add("--host", fields.get("host"))
    elif deploy_type == "ssh":
        add("--host", fields.get("host"))
        add("--port", fields.get("port") if str(fields.get("port")) != "22" else None)
        add("--user", fields.get("username"))
        add("--key", fields.get("cert_route"))
        add("--remote-path", fields.get("remote_repo_path"))
    elif deploy_type == "aws":
        add("--aws-region", fields.get("region"))
        add("--aws-ami", fields.get("ami_id"))
        add("--aws-instance-type", fields.get("instance_type"))
        add("--aws-instance-name", fields.get("instance_name"))
        add("--aws-security-group", fields.get("security_group"))
        add("--aws-key-name", fields.get("key_name"))
        add("--aws-user", fields.get("username"))
        add("--key", fields.get("ssh_key_path"))
        add("--aws-remote-path", fields.get("remote_path"))
    elif cloud_providers.is_cloud(deploy_type):
        add("--server-name", fields.get("server_name"))
        add("--server-size", fields.get("size"))
        add("--server-region", fields.get("region"))
        add("--key", fields.get("ssh_key_path"))
    if deploy_type in ("ssh", "aws", *cloud_providers.CLOUD_TYPES):
        add("--domain", fields.get("domain"))
        if (fields.get("domain") or "").strip():
            add("--acme-email", fields.get("acme_email"))
    return " ".join(parts)


def _https_settings(fields):
    """The domain and certificate email of the form as config keys (only those filled in)."""
    settings = {}
    if (fields.get("domain") or "").strip():
        settings["domain"] = fields["domain"].strip()
        if (fields.get("acme_email") or "").strip():
            settings["acmeEmail"] = fields["acme_email"].strip()
    return settings


def build_deploy_config(
    deploy_type, fields, name="test", version="1.0.0", dest_dir=None, gispublisher_root=None, overwrite_edited=False,
    zip_output=False,
):
    """Write a temporary GISPublisher config JSON and return its path.

    `fields` holds the plain string/int values collected from the deploy form
    for the given `deploy_type` ("local", "ssh", "aws", "hetzner" or "digitalocean") — pass {} for a
    generate-only run, which still needs a concrete `deploy.type` since
    gispublisher's main.js dereferences `config.deploy.type` unconditionally
    even when only generating.

    `dest_dir`, when given, writes the file there instead of the system temp
    directory — used for generate so the config's own parent directory can
    double as gispublisher's cwd (its --config resolution is cwd-relative,
    with no support for an absolute path), letting the CLI's "output" folder
    land in the user's chosen output directory instead of a temp one.

    `gispublisher_root`, when given, skips get_gispublisher_root()'s own
    lookup entirely (which otherwise spawns `npm root -g`) — callers that
    already resolved it via a requirements check (see qgispublisher_dialog's
    self._gispublisher_root) should pass it so this never blocks on a fresh
    npm subprocess right before a run starts.
    """
    if gispublisher_root is None:
        gispublisher_root = get_gispublisher_root()
    platform_dir = pathlib.Path(gispublisher_root) / "node_modules" / "@lbdudc" / "mini-lps" / "src" / "platform"

    base_json = {
        "name": name,
        "version": version,
        "platform": {
            "codePath": str(platform_dir / "code"),
            "featureModel": str(platform_dir / "model.xml"),
            "config": str(platform_dir / "config.json"),
            "extraJS": str(platform_dir / "extra.js"),
            "modelTransformation": str(platform_dir / "transformation.js"),
        },
    }

    if deploy_type == "local":
        deploy_section = {
            "deploy": {"type": "local"},
            "host": fields.get("host") or "http://localhost:80",
        }
    elif deploy_type == "ssh":
        deploy_section = {
            "deploy": {
                "type": "ssh",
                "host": fields["host"],
                "port": fields["port"],
                "username": fields["username"],
                "certRoute": fields["cert_route"],
                "remoteRepoPath": fields["remote_repo_path"],
                **_https_settings(fields),
            },
            "host": fields["host"],
        }
    elif deploy_type == "aws":
        deploy_section = {
            # The access keys are deliberately not here: they reach the CLI as
            # environment variables (core.credentials.deploy_environment)
            "deploy": {
                "type": "aws",
                "AWS_REGION": fields["region"],
                "AWS_AMI_ID": fields["ami_id"],
                "AWS_INSTANCE_TYPE": fields["instance_type"],
                "AWS_INSTANCE_NAME": fields["instance_name"],
                "AWS_SECURITY_GROUP_ID": fields["security_group"],
                "AWS_KEY_NAME": fields["key_name"],
                "AWS_USERNAME": fields["username"],
                "AWS_SSH_PRIVATE_KEY_PATH": fields["ssh_key_path"],
                "REMOTE_REPO_PATH": fields["remote_path"],
                **_https_settings(fields),
            }
        }
    elif cloud_providers.is_cloud(deploy_type):
        deploy_section = {
            # The API token is not here either: it reaches the CLI as HCLOUD_TOKEN /
            # DIGITALOCEAN_TOKEN (core.credentials.deploy_environment)
            "deploy": {
                "type": deploy_type,
                "serverName": fields["server_name"],
                "serverSize": fields["size"],
                "serverRegion": fields["region"],
                "certRoute": fields["ssh_key_path"],
                "username": "root",
                "remoteRepoPath": fields.get("remote_path") or cloud_providers.DEFAULT_REMOTE_PATH,
                **_https_settings(fields),
            }
        }
    else:
        raise ValueError(f"Unknown deployment type: {deploy_type}")

    # A redeploy keeps what people changed in the web app, unless told to replace it
    if overwrite_edited:
        deploy_section["deploy"] = {**deploy_section["deploy"], "overwriteEditedLayers": True}

    final_json = {**base_json, **deploy_section}
    if zip_output:
        # a generate run that also makes <name>-<version>.zip next to the generated app
        final_json["zip"] = True

    # The deploy section can still name key files and hosts — mkstemp (not
    # NamedTemporaryFile, which this used to reopen by path via a second open() call,
    # leaking its own file handle) gives us the fd to chmod before anything is written
    # to it, rather than relying on the platform default and hoping it's restrictive
    # enough.
    fd, path = tempfile.mkstemp(suffix=".json", dir=dest_dir)
    if sys.platform != "win32":
        os.chmod(path, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(final_json, f, indent=4)

    return path
