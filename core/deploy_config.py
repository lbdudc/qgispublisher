import json
import pathlib
import subprocess
import tempfile

from .dependencies_checker import find_npm


def get_gispublisher_root():
    """Return the install path of the @lbdudc/gis-publisher npm package."""
    npm_path = find_npm()
    result = subprocess.run(  # nosec B603 - npm_path is a fully-resolved path from shutil.which()
        [npm_path, "root", "-g"],
        capture_output=True,
        text=True,
    )
    npm_root = pathlib.Path(result.stdout.strip())
    return npm_root / "@lbdudc" / "gis-publisher"


def build_deploy_config(deploy_type, fields):
    """Write a temporary GISPublisher deploy config JSON and return its path.

    `fields` holds the plain string/int values collected from the deploy form
    for the given `deploy_type` ("local", "ssh", or "aws").
    """
    gispublisher_root = get_gispublisher_root()
    platform_dir = gispublisher_root / "node_modules" / "@lbdudc" / "mini-lps" / "src" / "platform"

    base_json = {
        "name": "test",
        "version": "2.0.0",
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
            "deploy": {
                "type": "aws",
                "AWS_ACCESS_KEY_ID": fields["access_key"],
                "AWS_SECRET_ACCESS_KEY": fields["secret_key"],
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

    final_json = {**base_json, **deploy_section}

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    with open(temp_file.name, "w") as f:
        json.dump(final_json, f, indent=4)

    return temp_file.name
