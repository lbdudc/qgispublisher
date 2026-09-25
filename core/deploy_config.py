import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

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


def deploy_problem(deploy_type, fields):
    """The first problem with the deploy form's values that would make the run fail
    anyway (after minutes of building), as a sentence for the user; None when fine."""
    if deploy_type == "ssh":
        host, remote_path = fields.get("host", ""), fields.get("remote_repo_path")
    elif deploy_type == "aws":
        host, remote_path = "", fields.get("remote_path")
    else:
        return None

    if host and (re.search(r"[\s/]", host.strip()) or "://" in host):
        return "The host must be a name or IP address (for example 203.0.113.5), not a URL."
    return remote_path_problem(remote_path)


def build_deploy_config(
    deploy_type, fields, name="test", version="1.0.0", dest_dir=None, gispublisher_root=None, overwrite_edited=False
):
    """Write a temporary GISPublisher config JSON and return its path.

    `fields` holds the plain string/int values collected from the deploy form
    for the given `deploy_type` ("local", "ssh", or "aws") — pass {} for a
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
            }
        }
    else:
        raise ValueError(f"Unknown deployment type: {deploy_type}")

    # A redeploy keeps what people changed in the web app, unless told to replace it
    if overwrite_edited:
        deploy_section["deploy"] = {**deploy_section["deploy"], "overwriteEditedLayers": True}

    final_json = {**base_json, **deploy_section}

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
