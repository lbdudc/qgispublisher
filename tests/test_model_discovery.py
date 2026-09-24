"""Unit tests for core.model_discovery — runnable outside QGIS:

    python -m unittest discover -s tests

_provider_models() (the only QGIS-touching function — it queries
QgsApplication.processingRegistry()) defers its qgis.core import to its own
body precisely so the rest of this module — ModelEntry, discover_folder_models,
discover_all_models's dedup logic, stage_model — stays importable and testable
here. discover_all_models is exercised by monkeypatching
discover_project_models/discover_profile_models directly, rather than through
_provider_models.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import model_discovery  # noqa: E402


class _FakeParam:
    def __init__(self, name, description=""):
        self._name = name
        self._description = description

    def name(self):
        return self._name

    def description(self):
        return self._description


class _FakeAlgorithm:
    def __init__(self, params=None, raise_on_params=False, to_file_result=True, to_file_raises=False):
        self._params = params or []
        self._raise_on_params = raise_on_params
        self._to_file_result = to_file_result
        self._to_file_raises = to_file_raises
        self.to_file_called_with = None

    def parameterDefinitions(self):
        if self._raise_on_params:
            raise RuntimeError("boom")
        return self._params

    def toFile(self, path):
        self.to_file_called_with = path
        if self._to_file_raises:
            raise RuntimeError("boom")
        if self._to_file_result:
            # A real QgsProcessingModelAlgorithm.toFile() writes the file;
            # match that so callers checking os.path.isfile see it too.
            with open(path, "w", encoding="utf-8") as f:
                f.write("{}")
        return self._to_file_result


class ModelEntryParameterSummaryTests(unittest.TestCase):
    def test_no_algorithm_returns_empty_string(self):
        entry = model_discovery.ModelEntry("id", "Name", "Group", "Project")
        self.assertEqual(entry.parameter_summary(), "")

    def test_unreadable_parameters_says_so_instead_of_blank(self):
        entry = model_discovery.ModelEntry(
            "id", "Name", "Group", "Project", algorithm=_FakeAlgorithm(raise_on_params=True)
        )
        self.assertEqual(entry.parameter_summary(), "Parameters unavailable (could not read this model's definition)")

    def test_no_parameters(self):
        entry = model_discovery.ModelEntry("id", "Name", "Group", "Project", algorithm=_FakeAlgorithm(params=[]))
        self.assertEqual(entry.parameter_summary(), "No parameters")

    def test_lists_parameter_descriptions_preferring_description_over_name(self):
        params = [_FakeParam("input_layer", "Input layer"), _FakeParam("threshold")]
        entry = model_discovery.ModelEntry("id", "Name", "Group", "Project", algorithm=_FakeAlgorithm(params=params))
        self.assertEqual(entry.parameter_summary(), "Parameters: Input layer, threshold")


class DiscoverFolderModelsTests(unittest.TestCase):
    def test_none_folder_returns_empty(self):
        self.assertEqual(model_discovery.discover_folder_models(None), [])

    def test_nonexistent_folder_returns_empty(self):
        self.assertEqual(model_discovery.discover_folder_models("/no/such/folder"), [])

    def test_only_model3_files_included_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("z_model.model3", "a_model.model3", "notes.txt"):
                with open(os.path.join(tmpdir, name), "w", encoding="utf-8") as f:
                    f.write("")
            entries = model_discovery.discover_folder_models(tmpdir)

        self.assertEqual([e.display_name for e in entries], ["a_model", "z_model"])
        for entry in entries:
            self.assertEqual(entry.source, model_discovery.SOURCE_FOLDER)
            self.assertTrue(entry.source_file_path.endswith(".model3"))
            self.assertTrue(entry.id.startswith("folder:"))


class DiscoverAllModelsTests(unittest.TestCase):
    def _entry(self, display_name, source):
        return model_discovery.ModelEntry(f"{source}:{display_name}", display_name, "", source)

    def test_project_models_always_included(self):
        project_entries = [self._entry("Model A", model_discovery.SOURCE_PROJECT)]
        with mock.patch.object(model_discovery, "discover_project_models", return_value=project_entries), \
             mock.patch.object(model_discovery, "discover_profile_models", return_value=[]):
            result = model_discovery.discover_all_models()
        self.assertEqual(result, project_entries)

    def test_profile_model_skipped_when_name_collides_with_project_model(self):
        project_entries = [self._entry("Model A", model_discovery.SOURCE_PROJECT)]
        profile_entries = [
            self._entry("Model A", model_discovery.SOURCE_PROFILE),  # dup, dropped
            self._entry("Model B", model_discovery.SOURCE_PROFILE),  # unique, kept
        ]
        with mock.patch.object(model_discovery, "discover_project_models", return_value=project_entries), \
             mock.patch.object(model_discovery, "discover_profile_models", return_value=profile_entries):
            result = model_discovery.discover_all_models()

        self.assertEqual([e.display_name for e in result], ["Model A", "Model B"])
        # The kept "Model A" is the project copy, not the profile duplicate.
        self.assertIs(result[0], project_entries[0])

    def test_extra_folder_models_deduped_against_project_and_profile(self):
        project_entries = [self._entry("Model A", model_discovery.SOURCE_PROJECT)]
        profile_entries = [self._entry("Model B", model_discovery.SOURCE_PROFILE)]
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("Model A.model3", "Model B.model3", "Model C.model3"):
                with open(os.path.join(tmpdir, name), "w", encoding="utf-8") as f:
                    f.write("")

            with mock.patch.object(model_discovery, "discover_project_models", return_value=project_entries), \
                 mock.patch.object(model_discovery, "discover_profile_models", return_value=profile_entries):
                result = model_discovery.discover_all_models(extra_folder=tmpdir)

        self.assertEqual([e.display_name for e in result], ["Model A", "Model B", "Model C"])
        self.assertEqual(result[2].source, model_discovery.SOURCE_FOLDER)


class StageModelTests(unittest.TestCase):
    def test_copies_existing_source_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = os.path.join(tmpdir, "src")
            dest_dir = os.path.join(tmpdir, "dest")
            os.makedirs(src_dir)
            src_path = os.path.join(src_dir, "original.model3")
            with open(src_path, "w", encoding="utf-8") as f:
                f.write("model-content")

            entry = model_discovery.ModelEntry("id", "My Model", "", model_discovery.SOURCE_PROFILE, src_path)
            dest_path = model_discovery.stage_model(entry, dest_dir)

            self.assertIsNotNone(dest_path)
            self.assertTrue(os.path.isfile(dest_path))
            with open(dest_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "model-content")

    def test_serializes_project_embedded_algorithm_with_no_backing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            algorithm = _FakeAlgorithm(to_file_result=True)
            entry = model_discovery.ModelEntry(
                "id", "My Model", "", model_discovery.SOURCE_PROJECT, source_file_path="", algorithm=algorithm
            )
            dest_path = model_discovery.stage_model(entry, tmpdir)

            self.assertIsNotNone(dest_path)
            # "My Model" -> "My_Model": stage_model replaces anything that
            # isn't alnum/-/_/. with "_", including the space.
            self.assertTrue(dest_path.endswith("My_Model.model3"))
            self.assertEqual(algorithm.to_file_called_with, dest_path)

    def test_returns_none_when_to_file_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entry = model_discovery.ModelEntry(
                "id", "My Model", "", model_discovery.SOURCE_PROJECT,
                algorithm=_FakeAlgorithm(to_file_result=False),
            )
            self.assertIsNone(model_discovery.stage_model(entry, tmpdir))

    def test_returns_none_when_to_file_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entry = model_discovery.ModelEntry(
                "id", "My Model", "", model_discovery.SOURCE_PROJECT,
                algorithm=_FakeAlgorithm(to_file_raises=True),
            )
            self.assertIsNone(model_discovery.stage_model(entry, tmpdir))

    def test_returns_none_when_neither_file_nor_algorithm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entry = model_discovery.ModelEntry("id", "My Model", "", model_discovery.SOURCE_PROJECT)
            self.assertIsNone(model_discovery.stage_model(entry, tmpdir))

    def test_display_name_sanitized_for_filesystem(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entry = model_discovery.ModelEntry(
                "id", 'weird/name: "quoted"?', "", model_discovery.SOURCE_PROJECT,
                algorithm=_FakeAlgorithm(to_file_result=True),
            )
            dest_path = model_discovery.stage_model(entry, tmpdir)
            self.assertIsNotNone(dest_path)
            basename = os.path.basename(dest_path)
            self.assertNotIn("/", basename)
            self.assertNotIn(":", basename)
            self.assertNotIn('"', basename)


# Shape captured from a real QGIS 4.2 run of the demo project's "modelo" model
# (QgsProcessingModelAlgorithm.toVariant(), trimmed to what analyze_model reads).
def _modelo_variant():
    def static(value):
        return [{"source": 2, "static_value": value}]

    return {
        "children": {
            "native:buffer_1": {
                "alg_id": "native:buffer",
                "params": {
                    "DISTANCE": static(2000.0),
                    "SEGMENTS": static(25),
                    "DISSOLVE": static(True),
                    "INPUT": [{"source": 0, "parameter_name": "centros_de_salud"}],
                },
            },
            "native:difference_1": {"alg_id": "native:difference", "params": {}},
        },
        "parameterDefinitions": {
            "centros_de_salud": {
                "parameter_type": "vector", "data_types": [0], "description": "Centros de salud",
            },
            "municipios": {
                "parameter_type": "vector", "data_types": [2], "description": "Municipios",
            },
            "zonas": {"parameter_type": "sink", "data_type": -1, "description": "Zonas"},
        },
    }


def _param_type(alg_id, name):
    return "distance" if name == "DISTANCE" else "number"


class AnalyzeModelTests(unittest.TestCase):
    def test_clean_model_with_matching_layers_has_no_warnings(self):
        warnings = model_discovery.analyze_model(
            _modelo_variant(),
            param_type_lookup=_param_type,
            layer_geometries={"point", "polygon"},
            processing_crs_geographic=False,
        )
        self.assertEqual(warnings, [])

    def test_fixed_distance_warns_on_geographic_data(self):
        warnings = model_discovery.analyze_model(
            _modelo_variant(), param_type_lookup=_param_type, processing_crs_geographic=True
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("2000", warnings[0])
        self.assertIn("degrees", warnings[0])

    def test_distance_check_needs_a_type_lookup(self):
        self.assertEqual(model_discovery.analyze_model(_modelo_variant()), [])

    def test_non_distance_and_boolean_static_values_are_ignored(self):
        variant = _modelo_variant()
        # SEGMENTS=25 and DISSOLVE=True are static too, but neither is a distance
        warnings = model_discovery.analyze_model(variant, param_type_lookup=_param_type)
        self.assertEqual(len(warnings), 1)

    def test_unsupported_provider_is_flagged(self):
        variant = {"children": {
            "grass7:v.buffer_1": {"alg_id": "grass7:v.buffer", "params": {}},
            "native:buffer_1": {"alg_id": "native:buffer", "params": {}},
        }}
        warnings = model_discovery.analyze_model(variant)
        self.assertEqual(len(warnings), 1)
        self.assertIn("grass7", warnings[0])

    def test_vector_input_without_matching_geometry(self):
        warnings = model_discovery.analyze_model(
            _modelo_variant(), layer_geometries={"point"}, processing_crs_geographic=False
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("Municipios", warnings[0])
        self.assertIn("polygon", warnings[0])

    def test_any_geometry_input_needs_some_vector_layer(self):
        variant = {"parameterDefinitions": {
            "in": {"parameter_type": "source", "data_types": [-1], "description": "Input"},
        }}
        self.assertEqual(model_discovery.analyze_model(variant, layer_geometries={"line"}), [])
        self.assertEqual(len(model_discovery.analyze_model(variant, layer_geometries=set())), 1)

    def test_input_matching_skipped_without_layers(self):
        self.assertEqual(
            model_discovery.analyze_model(_modelo_variant(), processing_crs_geographic=False), []
        )

    def test_empty_or_missing_variant(self):
        self.assertEqual(model_discovery.analyze_model(None), [])
        self.assertEqual(model_discovery.analyze_model({}), [])


if __name__ == "__main__":
    unittest.main()
