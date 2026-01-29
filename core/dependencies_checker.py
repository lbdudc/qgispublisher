import os, subprocess

def check_node_gispublisher():
    """Check Node.js and GISPublisher, raise Exception if missing."""
    node_path = find_node_windows()
    gispub_path = find_gispublisher_windows()
    return gispub_path

def find_node_windows():
    possible_paths = [r"C:\Program Files\nodejs\node.exe",
                      r"C:\Program Files (x86)\nodejs\node.exe"]
    for path in possible_paths:
        if os.path.exists(path):
            os.environ["PATH"] += os.pathsep + os.path.dirname(path)
            return path
    raise Exception("No se encontró Node.js. Instálalo desde https://nodejs.org/ y reinicia QGIS.")

def get_npm_prefix():
    npm_path = find_npm_windows()
    result = subprocess.run([npm_path, "config", "get", "prefix"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise Exception("No se pudo obtener el prefijo de npm.")
    return result.stdout.strip()

def find_gispublisher_windows():
    prefix = get_npm_prefix()
    possible = [os.path.join(prefix, "gispublisher.cmd"),
                os.path.join(prefix, "bin", "gispublisher.cmd")]
    for path in possible:
        if os.path.exists(path):
            return path
    raise Exception("GISPublisher no está instalado.")

def find_npm_windows():
    possible_paths = [r"C:\Program Files\nodejs\npm.cmd",
                      r"C:\Program Files (x86)\nodejs\npm.cmd",
                      os.path.expandvars(r"%APPDATA%\npm\npm.cmd")]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    raise Exception("No se encontró npm. Asegúrate de que Node.js esté instalado.")
