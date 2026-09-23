"""Real-file coverage of the catalog contract retained during the lint migration."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest


class CatalogContractTests(unittest.TestCase):
    def test_catalog_presence_parse_and_semantic_equality(self):
        script = Path(__file__).resolve().parents[2] / "scripts/check_contract_integrity.py"
        spec = importlib.util.spec_from_file_location("contract_integrity", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cases = [
            (None, '{}', 'data/models.json missing'),
            ('{}', None, 'web/public/models.json missing'),
            ('{', '{}', 'data/models.json: failed to parse'),
            ('{}', '{', 'web/public/models.json: failed to parse'),
            ('{"models": [1]}', '{"models": [2]}', 'out of sync'),
            ('{"a": 1, "b": 2}', '{"b":2,"a":1}', None),
        ]
        previous = Path.cwd()
        try:
            for authoritative, mirror, error in cases:
                with self.subTest(error=error), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    for relative, content in [('data/models.json', authoritative), ('web/public/models.json', mirror)]:
                        if content is not None:
                            path = root / relative
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text(content)
                    os.chdir(root)
                    errors = module.check_models_catalog_mirror_sync()
                    if error:
                        self.assertTrue(any(error in message for message in errors), errors)
                    else:
                        self.assertEqual(errors, [])
                    os.chdir(previous)
        finally:
            os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
