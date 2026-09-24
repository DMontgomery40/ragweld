"""Runner contracts: complete source coverage and honest provider results."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "jev_lint.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("jev_lint", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class JevLintTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "Portable Jev lint runner is not installed")
        self.lint = load_runner()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        self.policy = {
            "include": ["src/*.py", "src/*.tsx", "copy/*.json"],
            "exclude": ["src/generated/*"],
            "rules": [{"id": "rule", "question": "Does executable code import redis?"}],
        }

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args]).decode()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_selection_handles_staged_unstaged_new_deleted_and_ignored(self):
        self.write("src/base.py", "x = 1\n")
        self.write("src/deleted.py", "x = 1\n")
        self.write(".gitignore", "src/ignored.py\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.write("src/base.py", "x = 2\n")
        self.git("add", "src/base.py")
        self.write("src/new file.py", "x = 3\n")
        self.write("src/ignored.py", "secret = 1\n")
        self.write("src/generated/a.py", "x = 0\n")
        (self.root / "src/deleted.py").unlink()
        self.assertEqual(self.lint.select_files(self.root, self.policy), ["src/base.py", "src/new file.py"])
        self.assertEqual(self.lint.select_files(self.root, self.policy, staged=True), ["src/base.py"])

    def test_staged_source_is_not_replaced_by_unstaged_changes(self):
        self.write("src/a.py", "import redis\n")
        self.git("add", "src/a.py")
        self.write("src/a.py", "import json\n")
        batches = self.lint.build_batches(self.root, ["src/a.py"], self.policy, staged=True)
        self.assertEqual(batches[0]["files"][0]["content"], "import redis\n")

    def test_indexed_file_survives_unstaged_symlink_or_deletion(self):
        self.write("src/a.py", "import redis\n")
        self.git("add", "src/a.py")
        (self.root / "src/a.py").unlink()
        (self.root / "src/a.py").symlink_to(self.root / ".env")
        self.assertEqual(self.lint.select_files(self.root, self.policy, staged=True), ["src/a.py"])

    def test_committed_scope_reads_head_despite_unstaged_repair(self):
        self.write("src/a.py", "import json\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        base = self.git("rev-parse", "HEAD").strip()
        self.write("src/a.py", "import redis\n")
        self.git("add", ".")
        self.git("commit", "-qm", "change")
        self.write("src/a.py", "import json\n")
        names = self.lint.select_files(self.root, self.policy, base=base)
        batches = self.lint.build_batches(self.root, names, self.policy, snapshot="HEAD", base=base)
        self.assertEqual(batches[0]["files"][0]["content"], "import redis\n")

    def test_committed_scope_sends_only_changed_hunks_with_bounded_context(self):
        original = "".join(f"line {number}\n" for number in range(1, 201))
        self.write("src/a.py", original)
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        base = self.git("rev-parse", "HEAD").strip()
        changed = original.replace("line 100\n", "import redis  # changed line\n")
        self.write("src/a.py", changed)
        self.git("add", ".")
        self.git("commit", "-qm", "change")

        batches = self.lint.build_batches(
            self.root,
            ["src/a.py"],
            self.policy,
            snapshot="HEAD",
            base=base,
            context_lines=2,
        )

        chunks = [source for batch in batches for source in batch["files"]]
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["line"], 98)
        self.assertEqual(chunks[0]["changed_lines"], [100])
        self.assertIn("line 98\n", chunks[0]["content"])
        self.assertIn("import redis  # changed line\n", chunks[0]["content"])
        self.assertIn("line 102\n", chunks[0]["content"])
        self.assertNotIn("line 1\n", chunks[0]["content"])

        questions, _ = self.lint.build_questions(batches[0], self.policy)
        self.assertIn("newly added lines [100]", next(iter(questions.values()))["instructions"])

    def test_changed_hunks_preserve_increment_statements_and_line_numbers(self):
        self.write("src/App.tsx", "let renderCount = 0;\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        base = self.git("rev-parse", "HEAD").strip()
        self.write("src/App.tsx", "let renderCount = 0;\n++renderCount;\nconst done = true;\n")
        self.git("add", ".")
        self.git("commit", "-qm", "change")

        batches = self.lint.build_batches(
            self.root, ["src/App.tsx"], self.policy, snapshot="HEAD", base=base, context_lines=0,
        )

        chunk = batches[0]["files"][0]
        self.assertEqual(chunk["content"], "++renderCount;\nconst done = true;\n")
        self.assertEqual(chunk["changed_lines"], [2, 3])

    def test_file_scoped_rule_keeps_enclosing_control_flow(self):
        original = "if (!ready) return null;\n" + "\n" * 30
        self.write("src/App.tsx", original)
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        base = self.git("rev-parse", "HEAD").strip()
        self.write("src/App.tsx", original + "useEffect(() => {}, []);\n")
        self.git("add", ".")
        self.git("commit", "-qm", "change")
        self.policy["rules"][0].update(include=["src/*.tsx"], scope="file")

        batches = self.lint.build_batches(
            self.root, ["src/App.tsx"], self.policy, snapshot="HEAD", base=base, context_lines=2,
        )

        chunk = batches[0]["files"][0]
        self.assertEqual(chunk["line"], 1)
        self.assertNotIn("changed_lines", chunk)
        self.assertIn("if (!ready) return null;", chunk["content"])
        self.assertIn("useEffect(() => {}, []);", chunk["content"])

    def test_cloud_key_is_never_selected_for_custom_endpoint(self):
        for url in ["http://127.0.0.1:8080", "https://other.example", "https://api.typesafe.ai:8443", "https://api.typesafe.ai.evil.example"]:
            with self.subTest(url=url):
                self.assertFalse(self.lint.is_typesafe_endpoint(url))
        self.assertTrue(self.lint.is_typesafe_endpoint("https://api.typesafe.ai"))

    def test_transport_has_total_deadline_even_when_server_streams(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        import time

        class SlowServer(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.end_headers()
                try:
                    for value in b'{"answers": {}}':
                        self.wfile.write(bytes([value]))
                        self.wfile.flush()
                        time.sleep(.05)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowServer)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        started = time.monotonic()
        with self.assertRaises(self.lint.LintError):
            self.lint.request(f"http://127.0.0.1:{server.server_port}", "", {}, .2)
        self.assertLess(time.monotonic() - started, .7)

    def test_explicit_paths_cannot_escape_source_policy_or_follow_symlinks(self):
        self.write("src/a.py", "x = 1\n")
        self.write(".env", "TYPESAFE_API_KEY=private\n")
        (self.root / "src/link.py").symlink_to(self.root / ".env")
        for name in ["../outside.py", ".env", "src/link.py"]:
            with self.subTest(name=name), self.assertRaises(self.lint.LintError):
                self.lint.select_files(self.root, self.policy, paths=[name])

    def test_chunks_cover_all_source_without_silent_truncation(self):
        source = "αβ\n" * 2500 + "x" * 35000
        self.write("src/a.py", source)
        batches = self.lint.build_batches(self.root, ["src/a.py"], self.policy, max_chars=8000, max_batches=20)
        chunks = [f for batch in batches for f in batch["files"]]
        self.assertEqual("".join(f["content"] for f in chunks), source)
        self.assertTrue(all(len(json.dumps(batch, ensure_ascii=False)) <= 8000 for batch in batches))

    def test_unrelated_files_never_share_semantic_evidence(self):
        paths = ['src/a.py', 'src/b.py', 'src/c.py']
        for path in paths:
            self.write(path, 'x = 1\n')
        batches = self.lint.build_batches(self.root, paths, self.policy)
        self.assertEqual([sorted({f['path'] for f in b['files']}) for b in batches], [[p] for p in paths])

    def test_budget_overflow_is_an_error_not_partial_success(self):
        self.write("src/a.py", "x" * 30000)
        with self.assertRaises(self.lint.LintError):
            self.lint.build_batches(self.root, ["src/a.py"], self.policy, max_chars=8000, max_batches=1)

    def test_invalid_json_is_detected_before_semantic_request(self):
        self.write("copy/a.json", '{"broken":')
        with self.assertRaises(self.lint.LintError):
            self.lint.build_batches(self.root, ["copy/a.json"], self.policy)

    def test_invalid_provider_answers(self):
        invalid = [{}, {"rule": {"noul": .1}}, {"rule": {"type": "choice", "noul": .1}}]
        invalid += [{"rule": {"type": "noul", "noul": x}} for x in [None, True, "0.1", -1, 2, float("nan"), float("inf")]]
        for answers in invalid:
            with self.subTest(answers=answers), self.assertRaises(self.lint.LintError):
                self.lint.validate_answers({"answers": answers}, ["rule"])
        self.assertEqual(self.lint.validate_answers({"answers": {"rule": {"type": "noul", "noul": .95}}}, ["rule"]), {"rule": .95})

    def test_result_distinguishes_pass_review_and_violation(self):
        self.assertEqual(self.lint.classify(.1, .35, .8), "pass")
        self.assertEqual(self.lint.classify(.5, .35, .8), "review")
        self.assertEqual(self.lint.classify(.95, .35, .8), "violation")

    def test_question_scope_excludes_unrelated_files(self):
        self.policy["rules"][0]["include"] = ["src/*.py"]
        self.write("src/a.py", "import redis\n")
        self.write("src/App.tsx", "export default function App() { return null }\n")
        batch = self.lint.build_batches(self.root, ["src/a.py", "src/App.tsx"], self.policy)[0]
        questions, locations = self.lint.build_questions(batch, self.policy)
        self.assertEqual(len(questions), 1)
        self.assertEqual(next(iter(locations.values()))["path"], "src/a.py")


if __name__ == "__main__":
    unittest.main()
