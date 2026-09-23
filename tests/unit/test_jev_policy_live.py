"""Optional real-provider regression matrix: JEV_LIVE_TESTS=1 uv run pytest -q -s tests/unit/test_jev_policy_live.py."""
import importlib.util
import json
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get('JEV_LIVE_TESTS') == '1', 'requires explicit live Jev check')
class JevPolicyLiveTests(unittest.TestCase):
    def test_semantic_rules_distinguish_behavior_from_keywords(self):
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location('jev_lint', root / 'scripts/jev_lint.py')
        lint = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lint)
        policy = json.loads((root / '.jev-lint.json').read_text())
        cases = json.loads((root / "tests/fixtures/jev_lint_cases.json").read_text())
        key = os.environ.get('TYPESAFE_API_KEY') or lint.read_key(Path(os.environ.get('JEV_ENV_FILE', root / '.env'))) or lint.read_key(Path.home() / '.config/jev/env')
        self.assertTrue(key, 'Live semantic regression requires configured TypeSafe credentials')
        import time
        deadline = time.monotonic() + 90
        values = {}
        for i, (rule, path, code, violation) in enumerate(cases):
            batch = {'context': policy['context'], 'files': [
                {'path': path, 'line': 1, 'offset': 0, 'content': code}
            ]}
            questions, _ = lint.build_questions(batch, policy)
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, 'Live regression exhausted its 90-second budget')
            response = lint.request('https://api.typesafe.ai', key, {'model': os.environ.get('JEV_MODEL', 'jev-latest'), 'state': batch, 'questions': questions}, min(30, remaining))
            answers = lint.validate_answers(response, questions)
            values[f'f{i}_{rule}'] = answers[f'f0_{rule}']
        print(json.dumps({'model': response.get('model'), 'cases': len(cases), 'probabilities': values}, sort_keys=True))
        for i, (rule, path, code, violation) in enumerate(cases):
            probability = values[f'f{i}_{rule}']
            with self.subTest(rule=rule, violation=violation, path=path):
                status = lint.classify(probability, policy.get('review_threshold', .35), policy.get('violation_threshold', .8))
                # Both review and violation block the gate; a known bad example must never pass.
                if violation:
                    self.assertNotEqual(status, 'pass')
                else:
                    self.assertEqual(status, 'pass')


if __name__ == '__main__':
    unittest.main()
