import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.utils.config import (
    ConfigLoadError,
    ConfigValidationError,
    load_config,
    save_config,
)


class TestConfigPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name)
        self.config_file = self.config_dir / "config.json"
        self.config_patches = (
            patch("src.utils.config.CONF_DIR", str(self.config_dir)),
            patch("src.utils.config.CONF_FILE", str(self.config_file)),
        )
        for config_patch in self.config_patches:
            config_patch.start()

    def tearDown(self):
        for config_patch in reversed(self.config_patches):
            config_patch.stop()
        self.temp_dir.cleanup()

    def test_missing_config_is_created_from_defaults(self):
        with patch(
            "src.utils.config.save_config",
            side_effect=AssertionError("load_config must not reacquire its lock"),
        ):
            config = load_config()

        self.assertEqual(config["ai"]["preferred_model"], "ollama")
        self.assertEqual(json.loads(self.config_file.read_text(encoding="utf-8")), config)

    def test_invalid_json_raises_actionable_error_instead_of_using_defaults(self):
        self.config_file.write_text("{invalid", encoding="utf-8")

        with self.assertRaisesRegex(ConfigLoadError, "restore .*config.json.bak"):
            load_config()

    def test_invalid_config_schema_is_rejected(self):
        self.config_file.write_text(
            json.dumps({"ollama": {"model": 42}}), encoding="utf-8"
        )

        with self.assertRaisesRegex(ConfigLoadError, "ollama.model"):
            load_config()

    def test_invalid_theme_preference_is_rejected(self):
        self.config_file.write_text(
            json.dumps({"interface": {"theme": "sepia"}}), encoding="utf-8"
        )

        with self.assertRaisesRegex(ConfigLoadError, "interface.theme"):
            load_config()

    def test_save_keeps_previous_config_backup_and_replaces_atomically(self):
        original = {"ai": {"preferred_model": "ollama"}}
        self.config_file.write_text(json.dumps(original), encoding="utf-8")
        updated = {
            **original,
            "ollama": {"host": "http://localhost:11434", "model": "test-model"},
        }

        saved = save_config(updated)

        self.assertEqual(saved["ollama"]["model"], "test-model")
        self.assertEqual(json.loads(self.config_file.read_text(encoding="utf-8")), saved)
        self.assertEqual(
            json.loads(
                self.config_file.with_suffix(".json.bak").read_text(encoding="utf-8")
            ),
            original,
        )
        self.assertEqual(list(self.config_dir.glob("*.tmp")), [])

    def test_save_rejects_invalid_values_without_changing_existing_file(self):
        original = json.dumps({"ai": {"preferred_model": "ollama"}})
        self.config_file.write_text(original, encoding="utf-8")

        with self.assertRaises(ConfigValidationError):
            save_config({"ollama": {"model": ""}})

        self.assertEqual(self.config_file.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
