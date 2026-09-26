"""Live layers: a PostGIS table or a WFS layer that is *not* copied into the web app.

The app's own GeoServer connects to the source and draws it with the layer's QGIS style, so a live
layer follows the source with no republishing. It has no table in the app, so no list, search,
popup-from-table, editing or download. This module holds the QGIS-free part: reading a layer's
provider source string into the ``<name>.live.json`` sidecar that ``gispublisher`` reads back
(``gispublisher/src/live-util.js``), and the warnings that go with it.
"""

import re

PROVIDER_POSTGRES = "postgres"
PROVIDER_WFS = "WFS"

_LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0", ""}

# key=value where the value is 'quoted' (with \' inside), "quoted", or bare
_PAIR_RE = re.compile(r"""([A-Za-z_]+)=('(?:\\.|[^'\\])*'|"(?:[^"]|"")*"|\S+)""")
_TABLE_RE = re.compile(r'table=((?:"(?:[^"]|"")*"|[^\s.(]+)(?:\.(?:"(?:[^"]|"")*"|[^\s(]+))?)')


def _unquote(value):
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('""', '"')
    return value


def parse_source(source):
    """The ``key=value`` pairs of a QGIS provider source string (the ``table=`` part apart)."""
    text = source or ""
    pairs = {}
    for match in _PAIR_RE.finditer(text):
        pairs.setdefault(match.group(1), _unquote(match.group(2)))
    table = _TABLE_RE.search(text)
    if table:
        parts = re.findall(r'"((?:[^"]|"")*)"|([^.\s]+)', table.group(1))
        names = [(quoted.replace('""', '"') if quoted else bare) for quoted, bare in parts]
        pairs["_schema"], pairs["_table"] = (names[0], names[1]) if len(names) > 1 else ("public", names[0])
    return pairs


def _srid(pairs, fallback):
    try:
        value = int(pairs.get("srid", 0))
    except ValueError:
        value = 0
    return value if value > 0 else fallback


def can_be_live(provider):
    return provider in (PROVIDER_POSTGRES, PROVIDER_WFS)


def build_sidecar(provider, source, srid=4326, credentials=None):
    """The sidecar dict for a layer, or ``(None, reason)`` when it cannot be a live layer.

    ``credentials`` is an optional ``(user, password)`` for a source whose login lives in the QGIS
    authentication database rather than in the source string. Returns ``(sidecar, "")``.
    """
    pairs = parse_source(source)
    user, password = credentials or (None, None)
    user = pairs.get("user") or user or ""
    password = pairs.get("password") or password or ""

    if provider == PROVIDER_POSTGRES:
        if pairs.get("service"):
            return None, "it connects through a PostgreSQL service file, which the server cannot read"
        table = pairs.get("_table")
        if not pairs.get("dbname") or not table:
            return None, "it is not a plain table of a PostGIS database (a query layer cannot be kept live)"
        if pairs.get("sql"):
            return None, "it has a filter (sql=): a live layer shows the whole table"
        return {
            "kind": "postgis",
            "host": pairs.get("host", "localhost"),
            "port": int(pairs.get("port", 5432)) if str(pairs.get("port", "5432")).isdigit() else 5432,
            "database": pairs["dbname"],
            "schema": pairs.get("_schema", "public"),
            "table": table,
            "user": user,
            "password": password,
            "srid": _srid(pairs, srid),
        }, ""

    if provider == PROVIDER_WFS:
        url = pairs.get("url")
        type_name = pairs.get("typename") or pairs.get("typeName")
        if not url or not type_name:
            return None, "its WFS address or type name is missing"
        return {
            "kind": "wfs",
            "url": url,
            "typeName": type_name,
            "user": user,
            "password": password,
            "srid": _srid(pairs, srid),
        }, ""

    return None, "only PostGIS and WFS layers can be kept live"


def source_host(sidecar):
    """The host a sidecar's source runs on."""
    if sidecar.get("kind") == "postgis":
        return (sidecar.get("host") or "").strip().lower()
    match = re.match(r"^[a-z]+://(\[[^\]]+\]|[^/:?#]+)", sidecar.get("url", ""), re.I)
    return match.group(1).lower() if match else ""


def is_local_source(sidecar):
    return source_host(sidecar) in _LOOPBACK


def is_private_source(sidecar):
    host = source_host(sidecar)
    if host in _LOOPBACK:
        return True
    return bool(
        re.match(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.)", host)
        or "." not in host
        or host.endswith((".local", ".lan", ".internal"))
    )


def live_warnings(name, sidecar, deploy_type):
    """Plain-language warnings for a live layer given where the app is deployed."""
    warnings = []
    remote = deploy_type not in ("local", "generate", None)
    if remote and is_private_source(sidecar):
        warnings.append(
            f"{name}: its source ({source_host(sidecar) or 'this computer'}) is on a private network or on this "
            "computer, so the server the app is deployed to will not be able to reach it."
        )
    elif not remote and is_local_source(sidecar):
        warnings.append(
            f"{name}: its source is on this computer. The app reaches it as host.docker.internal, "
            "so the database must accept connections from Docker (listen on all addresses, not only localhost)."
        )
    if sidecar.get("password"):
        warnings.append(
            f"{name}: its password is stored in the app's server configuration (never in the pages people download)."
        )
    return warnings
