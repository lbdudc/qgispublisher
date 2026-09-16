"""Render a Vega spec to a self-contained HTML page using the plugin's bundled,
pinned vega / vega-lite / vega-embed libraries (resources/vega/), so the in-plugin
chart preview works fully offline and against the same renderer the generated
application ships (see mini-lps's client/_package.json: vega 5.22.1, vega-lite 5.2.0,
vega-embed 6.20.8).
"""

import json
import os

_RESOURCES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "vega")

_LIB_FILES = ("vega.min.js", "vega-lite.min.js", "vega-embed.min.js")

_lib_cache = {}


def _read_lib(filename):
    if filename not in _lib_cache:
        path = os.path.join(_RESOURCES_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            _lib_cache[filename] = f.read()
    return _lib_cache[filename]


def libraries_available():
    return all(os.path.isfile(os.path.join(_RESOURCES_DIR, name)) for name in _LIB_FILES)


def build_preview_html(spec):
    """Return a self-contained HTML document that renders `spec` with vega-embed."""
    scripts = "\n".join(f"<script>{_read_lib(name)}</script>" for name in _LIB_FILES)
    spec_json = json.dumps(spec)

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; background: #ffffff; }}
  #view {{ width: 100%; }}
  #error {{ color: #b00020; font-family: sans-serif; padding: 12px; white-space: pre-wrap; }}
</style>
{scripts}
</head>
<body>
<div id="view"></div>
<div id="error"></div>
<script>
  var spec = {spec_json};
  vegaEmbed('#view', spec, {{actions: false, renderer: 'svg'}}).catch(function(err) {{
    document.getElementById('error').textContent = 'Vega error: ' + err;
  }});
</script>
</body>
</html>
"""


def write_preview_html(spec, dest_path):
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(build_preview_html(spec))
    return dest_path
