import os
import subprocess
import sys
import shutil


def check_node_gispublisher():
    """Check Node.js and GISPublisher, raise Exception if missing."""
    node_result = find_node()
    if not node_result["installed"]:
        raise Exception(node_result["message"])
    gispub_path = find_gispublisher()
    return gispub_path


def find_node():
    """Locate the Node.js executable, cross-platform."""
    # shutil.which covers any platform where node is on PATH
    node = shutil.which("node") or shutil.which("node.exe")
    if node:
        node_dir = os.path.dirname(node)
        if node_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] += os.pathsep + node_dir
        return {"installed": True, "path": node}

    # Platform-specific fallback paths
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\nodejs\node.exe",
            r"C:\Program Files (x86)\nodejs\node.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/usr/local/bin/node",
            "/opt/homebrew/bin/node",
            "/usr/bin/node",
        ]
    else:  # Linux / other Unix
        candidates = [
            "/usr/bin/node",
            "/usr/local/bin/node",
            "/usr/bin/nodejs",
        ]

    for path in candidates:
        if os.path.exists(path):
            os.environ["PATH"] += os.pathsep + os.path.dirname(path)
            return {"installed": True, "path": path}

    return {
        "installed": False,
        "message": (
            "Node.js is not installed.<br>"
            "<a href='https://nodejs.org/en/download'>Install it here</a>"
        ),
    }


def find_npm():
    """Locate the npm executable, cross-platform."""
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm:
        return npm

    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\nodejs\npm.cmd",
            r"C:\Program Files (x86)\nodejs\npm.cmd",
            os.path.expandvars(r"%APPDATA%\npm\npm.cmd"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path

    raise Exception(
        "npm not found. Make sure Node.js is installed and on your PATH."
    )


def get_npm_prefix():
    npm_path = find_npm()
    result = subprocess.run(  # nosec B603 - npm_path is a fully-resolved path from shutil.which()
        [npm_path, "config", "get", "prefix"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise Exception("Could not determine npm prefix.")
    return result.stdout.strip()


def find_gispublisher():
    """Locate the gispublisher executable, cross-platform."""
    # Check PATH first
    gispub = shutil.which("gispublisher") or shutil.which("gispublisher.cmd")
    if gispub:
        return gispub

    # Derive from npm prefix
    try:
        prefix = get_npm_prefix()
        if sys.platform == "win32":
            candidates = [
                os.path.join(prefix, "gispublisher.cmd"),
                os.path.join(prefix, "bin", "gispublisher.cmd"),
            ]
        else:
            candidates = [
                os.path.join(prefix, "bin", "gispublisher"),
            ]
        for path in candidates:
            if os.path.exists(path):
                return path
    except Exception:  # nosec B110 - intentional; will raise below if gispublisher not found
        pass

    raise Exception(
        "GISPublisher is not installed. Run: npm install -g @lbdudc/gis-publisher"
    )


# ---------------------------------------------------------------------------
# Backward-compatible aliases (used by requirements_dialog.py)
# ---------------------------------------------------------------------------

def find_node_windows():
    return find_node()


def find_npm_windows():
    return find_npm()


def find_gispublisher_windows():
    return find_gispublisher()
