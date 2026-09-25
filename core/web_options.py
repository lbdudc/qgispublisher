"""What the QGIS user chooses about the generated web app itself, beyond the data:
its search / legend / download options and its branding (title, logo, colour,
basemap). Written into ``qgis-project.json`` (``project.options``,
``project.branding``) and read by ``gispublisher/src/options-util.js``.

Pure, like ``core.project_manifest``: plain data in, plain data out, no QGIS access,
so it is covered by ``tests/test_web_options.py``.
"""

import os
import re
import shutil

# The options and their defaults. Must match gispublisher's DEFAULT_OPTIONS: a manifest
# without an option means the default there too.
DEFAULT_OPTIONS = {
    "search": True,
    "geocoder": False,
    "legend": True,
    "downloads": True,
}

# id -> label. The ids are gispublisher's BASEMAPS catalogue (options-util.js).
BASEMAPS = {
    "osm": "OpenStreetMap",
    "esri-light": "Light gray (Esri)",
    "esri-dark": "Dark gray (Esri)",
    "esri-imagery": "Esri World Imagery",
    "opentopo": "OpenTopoMap",
}
DEFAULT_BASEMAP = "osm"

LOGO_EXTENSIONS = (".png", ".jpg", ".jpeg", ".svg", ".webp")
MAX_LOGO_BYTES = 2 * 1024 * 1024
BRANDING_DIRNAME = "branding"

_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def normalize_color(text):
    """``"#0B7A75"``-style text (the ``#`` is optional, case is kept as typed) as
    ``"#0b7a75"``, or ``None`` when it is not a six-digit hex colour."""
    match = _COLOR_RE.match((text or "").strip())
    return "#" + match.group(1).lower() if match else None


def build_options(raw):
    """``raw`` (possibly partial, possibly with junk) as a full options dict."""
    raw = raw or {}
    return {
        key: raw[key] if isinstance(raw.get(key), bool) else default
        for key, default in DEFAULT_OPTIONS.items()
    }


def logo_problem(path):
    """Why the file at ``path`` cannot be the app's logo, or ``None`` when it can
    (an empty path is fine: no logo)."""
    if not path:
        return None
    if not os.path.isfile(path):
        return "The logo file was not found."
    if os.path.splitext(path)[1].lower() not in LOGO_EXTENSIONS:
        return "The logo must be a PNG, JPG, SVG or WebP image."
    if os.path.getsize(path) > MAX_LOGO_BYTES:
        return f"The logo is too big: keep it under {MAX_LOGO_BYTES // (1024 * 1024)} MB."
    return None


def stage_logo(logo_path, temp_dir):
    """Copies the logo to ``<temp_dir>/branding/logo.<ext>`` and returns the file name
    inside ``branding`` (``"logo.png"``), or ``None`` when there is no usable logo."""
    if not logo_path or logo_problem(logo_path) is not None:
        return None
    extension = os.path.splitext(logo_path)[1].lower()
    name = "logo" + extension
    target_dir = os.path.join(temp_dir, BRANDING_DIRNAME)
    os.makedirs(target_dir, exist_ok=True)
    shutil.copyfile(logo_path, os.path.join(target_dir, name))
    return name


def build_branding(title=None, color=None, basemap=None, logo_name=None):
    """The manifest's ``project.branding``: only what is set and valid (an unknown
    basemap id counts as the default, which is written out only when it was chosen)."""
    branding = {}
    title = " ".join((title or "").split())
    if title:
        branding["title"] = title
    color = normalize_color(color)
    if color:
        branding["primaryColor"] = color
    if basemap in BASEMAPS:
        branding["basemap"] = basemap
    if logo_name:
        branding["logo"] = logo_name
    return branding


def project_info_extras(settings, temp_dir):
    """The ``options`` and ``branding`` entries to add to the manifest's project info.

    ``settings``: ``{"options": {...}, "title", "color", "basemap", "logo_path"}`` as
    the dialog collects it (every key optional); ``None`` gives the defaults, which is
    exactly what an older plugin produced. The logo is staged into ``temp_dir`` here.
    """
    settings = settings or {}
    logo_name = stage_logo(settings.get("logo_path"), temp_dir)
    extras = {"options": build_options(settings.get("options"))}
    branding = build_branding(
        settings.get("title"), settings.get("color"), settings.get("basemap"), logo_name
    )
    if branding:
        extras["branding"] = branding
    return extras
