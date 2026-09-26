import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import live_layers  # noqa: E402

PG = (
    "dbname='livegis' host=db.example.org port=5433 user='reader' password='p\\'w d' sslmode=disable "
    "key='id' srid=25829 type=LineString checkPrimaryKeyUnicity='1' table=\"public\".\"roads\" (geom) sql="
)
WFS = "pagingEnabled='true' typename='ns:rivers' url='https://example.org/geoserver/wfs' version='auto' srsname='EPSG:4326'"


class ParseSourceTests(unittest.TestCase):
    def test_postgres_pairs_and_table(self):
        pairs = live_layers.parse_source(PG)
        self.assertEqual(pairs["dbname"], "livegis")
        self.assertEqual(pairs["password"], "p'w d")
        self.assertEqual((pairs["_schema"], pairs["_table"]), ("public", "roads"))

    def test_table_without_schema(self):
        pairs = live_layers.parse_source("dbname='x' table=\"t\" (geom)")
        self.assertEqual((pairs["_schema"], pairs["_table"]), ("public", "t"))


class BuildSidecarTests(unittest.TestCase):
    def test_postgis(self):
        sidecar, reason = live_layers.build_sidecar("postgres", PG)
        self.assertEqual(reason, "")
        self.assertEqual(sidecar, {
            "kind": "postgis", "host": "db.example.org", "port": 5433, "database": "livegis", "schema": "public",
            "table": "roads", "user": "reader", "password": "p'w d", "srid": 25829,
        })

    def test_postgis_login_from_the_authentication_database(self):
        sidecar, _ = live_layers.build_sidecar("postgres", "dbname='g' host=h table=\"t\" (geom)", credentials=("u", "pw"))
        self.assertEqual((sidecar["user"], sidecar["password"], sidecar["srid"]), ("u", "pw", 4326))

    def test_postgis_refusals(self):
        self.assertIn("service", live_layers.build_sidecar("postgres", "service='s' table=\"t\" (geom)")[1])
        self.assertIn("filter", live_layers.build_sidecar("postgres", "dbname='g' table=\"t\" (geom) sql=id>3")[1])
        self.assertIn("query", live_layers.build_sidecar("postgres", "dbname='g' table=\"\" (geom)")[1])

    def test_wfs(self):
        sidecar, reason = live_layers.build_sidecar("WFS", WFS, srid=3857)
        self.assertEqual(reason, "")
        self.assertEqual(sidecar["url"], "https://example.org/geoserver/wfs")
        self.assertEqual((sidecar["typeName"], sidecar["srid"], sidecar["kind"]), ("ns:rivers", 3857, "wfs"))

    def test_other_providers(self):
        self.assertFalse(live_layers.can_be_live("ogr"))
        self.assertIsNone(live_layers.build_sidecar("ogr", "x.shp")[0])


class WarningsTests(unittest.TestCase):
    def test_private_source_on_a_remote_target(self):
        sidecar = live_layers.build_sidecar("postgres", "dbname='g' host=localhost table=\"t\" (geom)")[0]
        self.assertTrue(live_layers.live_warnings("Roads", sidecar, "ssh")[0].startswith("Roads: its source"))
        self.assertIn("host.docker.internal", live_layers.live_warnings("Roads", sidecar, "local")[0])

    def test_public_source_is_quiet_apart_from_the_password_note(self):
        sidecar = live_layers.build_sidecar("WFS", WFS)[0]
        self.assertEqual(live_layers.live_warnings("Rivers", sidecar, "aws"), [])

    def test_private_ranges(self):
        for host in ("10.0.0.5", "192.168.1.2", "172.20.0.1", "dbserver", "db.local"):
            self.assertTrue(live_layers.is_private_source({"kind": "postgis", "host": host}), host)
        self.assertFalse(live_layers.is_private_source({"kind": "postgis", "host": "db.example.org"}))


if __name__ == "__main__":
    unittest.main()
