import json
import os
import re
import subprocess
import sys
import shutil

# The CLI version this plugin is known to work against — bump this whenever a
# gispublisher/mini-lps/gisdsl change the plugin depends on is published, so an
# out-of-date CLI is flagged rather than failing (or silently misbehaving) deep
# inside the generation run.
REQUIRED_CLI_VERSION = "1.8.0"


def _windows_full_path():
    """Return a PATH string that includes entries from the Windows registry.

    QGIS may launch with a restricted PATH. Reading from the registry
    ensures we find executables installed in user-configured locations
    (e.g. C:\\nodejs, nvm-windows, Scoop, etc.).
    """
    try:
        import winreg
        parts = [os.environ.get("PATH", "")]
        for hive, subkey in [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, r"Environment"),
        ]:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, "Path")
                    parts.append(os.path.expandvars(val))
            except OSError:
                pass
        return os.pathsep.join(parts)
    except Exception:
        return os.environ.get("PATH", "")


def check_node_gispublisher():
    """Check Node.js and GISPublisher, raise Exception if missing."""
    node_result = find_node()
    if not node_result["installed"]:
        raise Exception(node_result["message"])
    gispub_path = find_gispublisher()
    return gispub_path


def find_ssh():
    """Locate the `ssh` client and make sure the CLI that the plugin starts can find it too.

    A deployment over ssh runs `ssh` and `scp` from the gispublisher CLI. QGIS on Windows starts with a
    restricted PATH that leaves out Windows' own OpenSSH (C:\\Windows\\System32\\OpenSSH), so, like
    find_node(), retry with the PATH of the Windows registry and add the folder to this process's PATH.
    Returns the path of `ssh`, or None.
    """
    ssh = shutil.which("ssh") or shutil.which("ssh.exe")
    if not ssh and sys.platform == "win32":
        win_path = _windows_full_path()
        ssh = shutil.which("ssh.exe", path=win_path) or shutil.which("ssh", path=win_path)
    if ssh:
        ssh_dir = os.path.dirname(ssh)
        if ssh_dir.lower() not in os.environ.get("PATH", "").lower():
            os.environ["PATH"] += os.pathsep + ssh_dir
    return ssh


def find_node():
    """Locate the Node.js executable, cross-platform."""
    # shutil.which covers any platform where node is on PATH
    node = shutil.which("node") or shutil.which("node.exe")
    # On Windows, QGIS may have a restricted PATH — retry with registry PATH
    if not node and sys.platform == "win32":
        win_path = _windows_full_path()
        node = shutil.which("node.exe", path=win_path) or shutil.which("node", path=win_path)
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
    # On Windows, QGIS may have a restricted PATH — retry with registry PATH
    if not npm and sys.platform == "win32":
        win_path = _windows_full_path()
        npm = shutil.which("npm.cmd", path=win_path) or shutil.which("npm", path=win_path)
    if npm:
        return npm

    # Ensure node's directory is on PATH, then retry.
    # This covers cases where find_npm() is called without find_node() first.
    node_result = find_node()
    if node_result["installed"]:
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if npm:
            return npm
        # Also look for npm alongside the node executable
        node_dir = os.path.dirname(node_result["path"])
        for name in ("npm", "npm.cmd"):
            candidate = os.path.join(node_dir, name)
            if os.path.exists(candidate):
                return candidate

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


def find_gispublisher(npm_prefix=None):
    """Locate the gispublisher executable, cross-platform.

    `npm_prefix`, if given, skips the `npm config get prefix` subprocess call
    (used by gather_requirements(), which resolves it once and threads it
    through every lookup that would otherwise repeat it).
    """
    # Check PATH first
    gispub = shutil.which("gispublisher") or shutil.which("gispublisher.cmd")
    if gispub:
        return gispub

    # Derive from npm prefix
    try:
        prefix = npm_prefix if npm_prefix is not None else get_npm_prefix()
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


def get_installed_gispublisher_version(gispub_path, npm_prefix=None):
    """Best-effort installed @lbdudc/gis-publisher version.

    Reads straight from the package's own package.json where possible (cheap,
    no subprocess), falling back to spawning `gispub_path --version` — which is
    what the CLI itself answers with, wired automatically by meow's
    `importMeta` (gispublisher/src/cli.js). Returns None rather than raising:
    an unknown installed version shouldn't block the rest of check_requirements.

    `npm_prefix`, if given, skips the `npm config get prefix` subprocess call
    (see find_gispublisher's docstring — same rationale).
    """
    candidates = []
    try:
        prefix = npm_prefix if npm_prefix is not None else get_npm_prefix()
        if sys.platform == "win32":
            candidates.append(os.path.join(prefix, "node_modules", "@lbdudc", "gis-publisher", "package.json"))
        else:
            candidates.append(os.path.join(prefix, "lib", "node_modules", "@lbdudc", "gis-publisher", "package.json"))
    except Exception:  # nosec B110 - fall through to the next candidate
        pass

    try:
        # Deferred import: deploy_config imports find_npm from this module, so a
        # module-level import here would be circular.
        from .deploy_config import get_gispublisher_root
        candidates.append(os.path.join(str(get_gispublisher_root(npm_prefix)), "package.json"))
    except Exception:  # nosec B110
        pass

    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                version = json.load(f).get("version")
            if version:
                return version
        except Exception:  # nosec B112 - try the next candidate / final fallback
            continue

    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(  # nosec B603 - gispub_path is a fully-resolved path from find_gispublisher()
            [gispub_path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            **kwargs,
        )
        version = result.stdout.strip()
        if version:
            return version
    except Exception:  # nosec B110 - version stays unknown, not fatal
        pass

    return None


_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+")


def compare_versions(a, b):
    """Compare two dotted version strings (any prerelease/build suffix is
    ignored). Returns -1, 0 or 1. Returns None if either string doesn't parse
    as a version, so callers can tell "unknown" apart from "equal"."""

    def _parse(v):
        if not v:
            return None
        match = _VERSION_RE.match(v.strip())
        if not match:
            return None
        return tuple(int(p) for p in match.group(0).split("."))

    parsed_a, parsed_b = _parse(a), _parse(b)
    if parsed_a is None or parsed_b is None:
        return None
    if parsed_a < parsed_b:
        return -1
    if parsed_a > parsed_b:
        return 1
    return 0


def get_latest_gispublisher_version(timeout=20):
    """Ask npm for the latest published @lbdudc/gis-publisher version.

    Raises on any failure (offline, npm missing, timeout) — this is meant to be
    run from a background thread whose caller swallows the error silently, since
    QGIS is frequently used offline and a failed *update check* is not itself a
    problem worth interrupting the user over.
    """
    npm_path = find_npm()
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    result = subprocess.run(  # nosec B603 - npm_path is a fully-resolved path from shutil.which()
        [npm_path, "view", "@lbdudc/gis-publisher", "version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        **kwargs,
    )
    if result.returncode != 0:
        raise Exception(f"npm view failed: {(result.stderr or '').strip() or result.returncode}")
    version = result.stdout.strip()
    if not version:
        raise Exception("npm view returned no version.")
    return version


UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60


def should_check_for_update(last_check_epoch, now_epoch, interval_seconds=UPDATE_CHECK_INTERVAL_SECONDS):
    """Pure decision behind the "at most once every 24h" background npm check —
    kept separate from the QgsSettings read/write around it so it's covered by
    the QGIS-free test suite. `last_check_epoch` of None/0 (never checked) always
    returns True."""
    if not last_check_epoch:
        return True
    return (now_epoch - last_check_epoch) >= interval_seconds


def gather_requirements():
    """Run every Node.js/GISPublisher presence-and-version check in one pass.

    Between find_node, find_gispublisher, get_installed_gispublisher_version and
    (transitively) get_gispublisher_root, this can spawn several npm/node
    subprocesses — each of which routinely takes a second or more on Windows
    (cmd.exe + npm's own startup cost). This resolves the npm prefix at most
    once and threads it through every lookup that would otherwise repeat it,
    and is meant to be called from a background QThread
    (qgispublisher_dialog.RequirementsCheckThread) — never the UI thread.
    """
    node_result = find_node()

    npm_prefix = None
    try:
        npm_prefix = get_npm_prefix()
    except Exception:  # nosec B110 - individual lookups below fall back on their own
        pass

    try:
        gispub_path = find_gispublisher(npm_prefix=npm_prefix)
        gispub_ok = True
        gispub_message = f"GISPublisher found at: {gispub_path}"
    except Exception as e:
        gispub_path = None
        gispub_ok = False
        gispub_message = str(e)

    installed_version = (
        get_installed_gispublisher_version(gispub_path, npm_prefix=npm_prefix)
        if gispub_ok else None
    )

    gispublisher_root = None
    if gispub_ok:
        try:
            # Deferred import: see get_installed_gispublisher_version's docstring.
            from .deploy_config import get_gispublisher_root
            gispublisher_root = str(get_gispublisher_root(npm_prefix))
        except Exception:  # nosec B110 - build_deploy_config() falls back to its own lookup
            gispublisher_root = None

    return {
        "node_result": node_result,
        "gispub_path": gispub_path,
        "gispub_ok": gispub_ok,
        "gispub_message": gispub_message,
        "installed_version": installed_version,
        "gispublisher_root": gispublisher_root,
    }
