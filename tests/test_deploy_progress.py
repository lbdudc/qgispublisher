"""Unit tests for core.deploy_progress and core.deploy_errors — runnable outside QGIS:

    python -m unittest discover -s tests
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import deploy_errors, deploy_progress as dp  # noqa: E402


def line(**event):
    return dp.PROTOCOL_PREFIX + json.dumps(event)


class ParseLineTests(unittest.TestCase):
    def test_parses_an_event(self):
        event = dp.parse_line(line(event="step", id="read", status="running"))
        self.assertEqual(event["id"], "read")

    def test_ignores_ordinary_output_and_garbage(self):
        for text in ["", None, "Running gispublisher for folder x", "@@gp {not json", '@@gp [1, 2]', '@@gp {"a": 1}']:
            self.assertIsNone(dp.parse_line(text), text)

    def test_tolerates_leading_noise(self):
        self.assertEqual(dp.parse_line("[stdout] " + line(event="result", url="u"))["url"], "u")


class LineBufferTests(unittest.TestCase):
    def test_reassembles_lines_split_across_chunks(self):
        buffer = dp.LineBuffer()
        self.assertEqual(buffer.feed("one\ntw"), ["one"])
        self.assertEqual(buffer.feed("o\r\nthree"), ["two"])
        self.assertEqual(buffer.flush(), ["three"])
        self.assertEqual(buffer.flush(), [])


class DeployProgressTests(unittest.TestCase):
    def make(self):
        progress = dp.DeployProgress()
        progress.set_local_steps([("export", "Export layers"), ("stage", "Stage charts & models")])
        return progress

    def test_plan_appends_cli_steps_after_local_ones(self):
        progress = self.make()
        progress.set_local_status("export", dp.DONE)
        progress.apply({"event": "plan", "steps": [{"id": "read", "label": "Read"}, {"id": "wait", "label": "Wait"}]})
        self.assertEqual([s.id for s in progress.steps], ["export", "stage", "read", "wait"])
        self.assertEqual(progress.steps[0].status, dp.DONE)  # local status survives the plan
        self.assertTrue(progress.cli_reported)

    def test_step_events_update_status_and_progress(self):
        progress = self.make()
        progress.apply({"event": "plan", "steps": [{"id": "read", "label": "Read"}]})
        progress.set_local_status("export", dp.DONE)
        progress.set_local_status("stage", dp.DONE)
        self.assertEqual(progress.current.id, "read")
        progress.apply({"event": "step", "id": "read", "status": "running"})
        self.assertEqual(progress.current.id, "read")
        self.assertAlmostEqual(progress.fraction, 2 / 3)
        progress.apply({"event": "step", "id": "read", "status": "done", "durationMs": 1500})
        self.assertEqual(progress.fraction, 1.0)
        self.assertEqual(progress.steps[-1].duration_ms, 1500)

    def test_smooth_fraction_gives_the_running_step_half_credit(self):
        progress = dp.DeployProgress()
        progress.apply({"event": "plan", "steps": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]})
        self.assertEqual(progress.smooth_fraction, 0.0)
        progress.apply({"event": "step", "id": "a", "status": "done"})
        progress.apply({"event": "step", "id": "b", "status": "running"})
        self.assertEqual(progress.smooth_fraction, 0.75)
        progress.apply({"event": "step", "id": "b", "status": "done"})
        self.assertEqual(progress.smooth_fraction, 1.0)

    def test_skipped_counts_as_finished(self):
        progress = dp.DeployProgress()
        progress.apply({"event": "step", "id": "a", "label": "A", "status": "skipped", "detail": "nothing to do"})
        self.assertEqual(progress.fraction, 1.0)
        self.assertEqual(progress.steps[0].detail, "nothing to do")

    def test_unknown_step_is_appended(self):
        progress = dp.DeployProgress()
        progress.apply({"event": "step", "id": "x", "label": "X", "status": "running"})
        self.assertEqual([s.id for s in progress.steps], ["x"])

    def test_services_result_and_error(self):
        progress = dp.DeployProgress()
        progress.apply({"event": "services", "services": [
            {"name": "db", "status": "ready"}, {"name": "server", "status": "pending"}, {"name": "web", "status": "pending"},
        ]})
        self.assertEqual(progress.services_summary(), (1, 3, ["server", "web"]))
        progress.apply({"event": "result", "url": "http://localhost", "outputDir": "/o"})
        self.assertEqual((progress.url, progress.output_dir), ("http://localhost", "/o"))
        progress.apply({"event": "error", "step": "wait", "message": "boom", "detail": "stack"})
        self.assertEqual(progress.error["message"], "boom")

    def test_a_zip_result_carries_the_file_not_a_url(self):
        progress = dp.DeployProgress()
        progress.apply({"event": "result", "outputDir": "/o", "file": "/tmp/app-1.0.0.zip"})
        self.assertEqual(progress.zip_file, "/tmp/app-1.0.0.zip")
        self.assertEqual(progress.url, "")
        other = dp.DeployProgress()
        other.apply({"event": "result", "url": "https://x.org", "outputDir": "/o"})
        self.assertEqual(other.zip_file, "")

    def test_no_steps_means_no_fraction(self):
        self.assertIsNone(dp.DeployProgress().fraction)

    def test_failed_step(self):
        progress = dp.DeployProgress()
        progress.apply({"event": "step", "id": "a", "label": "A", "status": "failed", "detail": "no"})
        self.assertEqual(progress.failed_step.id, "a")

    def test_unknown_event_is_not_a_change(self):
        self.assertFalse(dp.DeployProgress().apply({"event": "log", "line": "x"}))

    def test_format_duration(self):
        self.assertEqual(dp.format_duration(4.2), "4s")
        self.assertEqual(dp.format_duration(184), "3m 04s")


class ExplainTests(unittest.TestCase):
    def check(self, text, title_part):
        explanation = deploy_errors.explain(text)
        self.assertIsNotNone(explanation, text)
        self.assertIn(title_part, explanation.title)
        self.assertTrue(explanation.hint)

    def test_known_failures(self):
        self.check("Docker is not running. Start Docker Desktop", "Docker is not running")
        self.check("error during connect: open //./pipe/dockerDesktopLinuxEngine", "Docker is not running")
        self.check("Docker is not installed (the `docker` command was not found).", "not installed")
        self.check("Bind for 0.0.0.0:80 failed: port is already allocated", "Port 80")
        self.check("Permission denied (publickey,password).", "SSH authentication")
        self.check("Could not connect via ssh to u@h: Connection timed out", "Could not reach")
        self.check("Passwordless sudo is required on the server", "passwordless sudo")
        self.check("Service(s) failed: server, geoserver\n--- server ---", "server, geoserver failed")
        self.check("Timed out waiting for services: geoserver", "did not become ready")
        self.check("no space left on device", "disk space")
        self.check("line 3:10 no viable alternative at input 'CREATE ENTITY point'", "could not read")

    def test_docker_missing_wins_over_generic_connection_text(self):
        self.assertIn("not installed", deploy_errors.explain("Command not found: docker").title)

    def test_unknown_and_empty(self):
        self.assertIsNone(deploy_errors.explain("something odd happened"))
        self.assertIsNone(deploy_errors.explain("", None))

    def test_uses_all_texts(self):
        self.assertIsNotNone(deploy_errors.explain("failed", "port is already allocated"))

    def test_last_error_line(self):
        lines = ["starting", "@@gp {}", "Error: it broke", "cleanup done", ""]
        self.assertEqual(deploy_errors.last_error_line(lines), "Error: it broke")
        self.assertEqual(deploy_errors.last_error_line(["a", "b"]), "b")
        self.assertEqual(deploy_errors.last_error_line([]), "")


class EditAccountTests(unittest.TestCase):
    def test_result_carries_the_editing_account(self):
        progress = dp.DeployProgress()
        progress.apply({"event": "result", "url": "u", "outputDir": "/o", "editUser": "editor", "editPassword": "pw123"})
        self.assertEqual((progress.edit_user, progress.edit_password), ("editor", "pw123"))

    def test_a_result_without_one_leaves_it_empty(self):
        progress = dp.DeployProgress()
        progress.apply({"event": "result", "url": "u", "outputDir": "/o"})
        self.assertEqual((progress.edit_user, progress.edit_password), ("", ""))


if __name__ == "__main__":
    unittest.main()
