"""Unit tests for core.state_store — runnable outside QGIS:

    python -m unittest discover -s tests

Project-selection tests use a minimal fake standing in for QgsProject's
writeEntry/readEntry/readListEntry/readBoolEntry custom-properties API — the
same shape state_store.py itself relies on, without needing a real QGIS
project. History tests monkeypatch _history_path() to a temp file, so the
qgis.core import deferred inside it (see model_discovery.py's own comment for
the same convention) never actually runs.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import state_store  # noqa: E402


class _FakeProject:
    """Backs QgsProject's custom-properties calls with a plain dict, keyed the
    same way (scope, key) -> value, with the same "(value, ok)" read shape."""

    def __init__(self):
        self._entries = {}

    def writeEntry(self, scope, key, value):
        self._entries[(scope, key)] = value

    def readEntry(self, scope, key, default=""):
        found = (scope, key) in self._entries
        return (self._entries.get((scope, key), default), found)

    def readListEntry(self, scope, key, default=None):
        found = (scope, key) in self._entries
        return (self._entries.get((scope, key), list(default or [])), found)

    def readBoolEntry(self, scope, key, default=False):
        found = (scope, key) in self._entries
        return (self._entries.get((scope, key), default), found)


class ProjectSelectionTests(unittest.TestCase):
    def _selection(self, **overrides):
        base = {
            "app_name": "MyApp",
            "app_version": "1.2.3",
            "layer_ids": ["layer1", "layer2"],
            "model_ids": ["model1"],
            "chart_folder": "/charts",
            "chart_files": ["a.json", "b.json"],
            "model_folder": "/models",
            "processing_crs": "EPSG:25829",
            "use_project_crs": True,
            "output_dir": "/out",
            "action": "deploy",
            "deploy_type": "ssh",
        }
        base.update(overrides)
        return base

    def test_web_options_round_trip_and_survive_junk(self):
        project = _FakeProject()
        web = {"options": {"search": False}, "title": "Río", "color": "#112233", "basemap": "carto-dark"}
        state_store.save_project_selection(project, self._selection(web_options=web))
        self.assertEqual(state_store.load_project_selection(project)["web_options"], web)

        project.writeEntry(state_store.SCOPE, "web_options", "{not json")
        self.assertEqual(state_store.load_project_selection(project)["web_options"], {})
        project.writeEntry(state_store.SCOPE, "web_options", "[1, 2]")
        self.assertEqual(state_store.load_project_selection(project)["web_options"], {})

    def test_projects_saved_before_web_options_load_an_empty_dict(self):
        project = _FakeProject()
        state_store.save_project_selection(project, self._selection())
        self.assertEqual(state_store.load_project_selection(project)["web_options"], {})

    def test_has_saved_selection_false_before_any_save(self):
        self.assertFalse(state_store.has_saved_selection(_FakeProject()))

    def test_has_saved_selection_true_after_save(self):
        project = _FakeProject()
        state_store.save_project_selection(project, self._selection())
        self.assertTrue(state_store.has_saved_selection(project))

    def test_round_trip_preserves_every_field(self):
        project = _FakeProject()
        selection = self._selection()
        state_store.save_project_selection(project, selection)
        loaded = state_store.load_project_selection(project)
        for key, value in selection.items():
            self.assertEqual(loaded[key], value, f"field {key!r} did not round-trip")

    def test_chart_files_none_means_everything_round_trips_as_none(self):
        project = _FakeProject()
        state_store.save_project_selection(project, self._selection(chart_files=None))
        loaded = state_store.load_project_selection(project)
        self.assertIsNone(loaded["chart_files"])

    def test_chart_files_empty_list_is_distinct_from_none(self):
        project = _FakeProject()
        state_store.save_project_selection(project, self._selection(chart_files=[]))
        loaded = state_store.load_project_selection(project)
        self.assertEqual(loaded["chart_files"], [])

    def test_missing_optional_fields_default_sensibly(self):
        project = _FakeProject()
        loaded = state_store.load_project_selection(project)
        self.assertEqual(loaded["layer_ids"], [])
        self.assertEqual(loaded["action"], "generate")
        self.assertEqual(loaded["deploy_type"], "local")
        self.assertIsNone(loaded["chart_files"])  # chart_files_all defaults True


class RunHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        history_path = os.path.join(self._tmpdir.name, "run_history.json")
        patcher = mock.patch.object(state_store, "_history_path", return_value=history_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmpdir.cleanup)

    def test_load_run_history_empty_when_no_file_yet(self):
        self.assertEqual(state_store.load_run_history(), [])

    def test_append_run_record_generate(self):
        record = state_store.append_run_record(
            run_type="generate",
            project_title="MyProject",
            layer_count=3,
            chart_count=1,
            model_count=0,
            exit_code=0,
            duration_seconds=12.34,
            log_lines=["line1", "line2"],
            output_dir="/out",
        )
        self.assertEqual(record["run_type"], "generate")
        self.assertEqual(record["output_dir"], "/out")
        self.assertEqual(record["deploy_type"], "")
        self.assertEqual(record["host"], "")
        self.assertEqual(record["duration_seconds"], 12.3)  # rounded to 1 decimal
        self.assertEqual(state_store.load_run_history(), [record])

    def test_deploy_secrets_never_persisted_to_restorable_fields(self):
        """The whole point of _RESTORABLE_DEPLOY_FIELDS: only non-secret fields
        make it into the on-disk record. AWS credentials/SSH key paths must
        never round-trip through history."""
        record = state_store.append_run_record(
            run_type="deploy",
            project_title="MyProject",
            deploy_type="aws",
            host="",
            layer_count=1,
            chart_count=0,
            model_count=0,
            exit_code=0,
            duration_seconds=5.0,
            log_lines=[],
            deploy_fields={
                "access_key": "AKIA_SECRET",
                "secret_key": "very_secret",  # pragma: allowlist secret
                "region": "eu-west-1",
                "ami_id": "ami-123",
                "ssh_key_path": "/keys/aws.pem",
            },
        )
        restorable = record["restorable_fields"]
        self.assertNotIn("access_key", restorable)
        self.assertNotIn("secret_key", restorable)
        self.assertNotIn("ssh_key_path", restorable)
        self.assertEqual(restorable.get("region"), "eu-west-1")
        self.assertEqual(restorable.get("ami_id"), "ami-123")

    def test_ssh_restorable_fields_exclude_username_and_cert_path(self):
        record = state_store.append_run_record(
            run_type="deploy",
            project_title="MyProject",
            deploy_type="ssh",
            host="1.2.3.4",
            layer_count=1,
            chart_count=0,
            model_count=0,
            exit_code=0,
            duration_seconds=1.0,
            log_lines=[],
            deploy_fields={
                "host": "1.2.3.4",
                "port": 22,
                "username": "deploy",
                "cert_route": "/keys/id_rsa",
                "remote_repo_path": "/srv/app",
            },
        )
        restorable = record["restorable_fields"]
        self.assertNotIn("username", restorable)
        self.assertNotIn("cert_route", restorable)
        self.assertEqual(restorable.get("host"), "1.2.3.4")
        self.assertEqual(restorable.get("port"), 22)
        self.assertEqual(restorable.get("remote_repo_path"), "/srv/app")

    def test_log_tail_truncated_to_last_history_log_lines(self):
        log_lines = [f"line{i}" for i in range(state_store.HISTORY_LOG_LINES + 10)]
        record = state_store.append_run_record(
            run_type="generate", project_title="p", layer_count=0, chart_count=0,
            model_count=0, exit_code=0, duration_seconds=None, log_lines=log_lines,
        )
        self.assertEqual(len(record["log_tail"]), state_store.HISTORY_LOG_LINES)
        self.assertEqual(record["log_tail"], log_lines[-state_store.HISTORY_LOG_LINES:])

    def test_history_capped_at_max_entries(self):
        for i in range(state_store.HISTORY_MAX_ENTRIES + 5):
            state_store.append_run_record(
                run_type="generate", project_title=f"p{i}", layer_count=0, chart_count=0,
                model_count=0, exit_code=0, duration_seconds=None, log_lines=[],
            )
        records = state_store.load_run_history()
        self.assertEqual(len(records), state_store.HISTORY_MAX_ENTRIES)
        # Oldest entries (p0..p4) are the ones trimmed — most recent kept.
        self.assertEqual(records[-1]["project_title"], f"p{state_store.HISTORY_MAX_ENTRIES + 4}")

    def test_clear_run_history_empties_it(self):
        state_store.append_run_record(
            run_type="generate", project_title="p", layer_count=0, chart_count=0,
            model_count=0, exit_code=0, duration_seconds=None, log_lines=[],
        )
        state_store.clear_run_history()
        self.assertEqual(state_store.load_run_history(), [])


if __name__ == "__main__":
    unittest.main()
