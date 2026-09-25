"""The plugin side of "Update data only" that needs no QGIS: what the refusals of the CLI
are explained as (core.deploy_errors)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import deploy_errors  # noqa: E402


class UpdateDataExplanationTests(unittest.TestCase):
    def test_changed_layers_say_to_deploy_again(self):
        message = "The layers' fields changed since the last deployment (...): use Deploy, the app has to be regenerated."
        explanation = deploy_errors.explain(message)
        self.assertEqual(explanation.title, "The data can't be updated on its own")
        self.assertIn("Deploy", explanation.hint)

    def test_added_layers_are_the_same_case(self):
        message = "Layers were added or removed since the last deployment (c.zip): use Deploy, the app has to be regenerated."
        self.assertEqual(deploy_errors.explain(message).title, "The data can't be updated on its own")

    def test_nothing_deployed_yet(self):
        for message in (
            "This app has not been deployed from here yet: deploy it first, then update its data.",
            "Nothing is deployed in /home/u/app on the server: deploy the app first.",
        ):
            self.assertEqual(deploy_errors.explain(message).title, "There is nothing to update yet", message)

    def test_app_not_running(self):
        for message in (
            "The app is not running: deploy it first (updating the data needs the running server).",
            "The app is not running on the server: deploy it first",
        ):
            self.assertEqual(deploy_errors.explain(message).title, "The app is not running", message)


if __name__ == "__main__":
    unittest.main()
