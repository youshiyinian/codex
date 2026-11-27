#!/usr/bin/env python3
"""i18n/apply.py 的单元测试。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import apply as i18n_apply


class ApplyHelperTests(unittest.TestCase):
    def test_is_test_file_handles_test_directories(self):
        self.assertTrue(i18n_apply.is_test_file("codex-rs/tui/src/chatwidget/tests/foo.rs"))
        self.assertTrue(i18n_apply.is_test_file("codex-rs/tui/src/chatwidget/realtime_tests/speech.rs"))
        self.assertTrue(i18n_apply.is_test_file("codex-rs/tui/src/foo_test/bar.rs"))
        self.assertTrue(i18n_apply.is_test_file("codex-rs/tui/src/foo_tests.rs"))
        self.assertFalse(i18n_apply.is_test_file("codex-rs/tui/src/chatwidget/rendering.rs"))

    def test_load_json_checked_detects_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dup.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"a": {"Hello": "你好", "Hello": "您好"}}\n')
            errors = []
            i18n_apply.load_json_checked(path, errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("重复的键", errors[0])
            self.assertIn("Hello", errors[0])

    def test_find_literals_skips_raw_byte_and_comments(self):
        src = (
            '// "comment"\n'
            '/* "block" */\n'
            'let a = "plain";\n'
            'let b = r#"raw"#;\n'
            'let c = b"bytes";\n'
            'let d = c"cstr";\n'
        )
        found = [src[s:e] for s, e in i18n_apply.find_literals(src)]
        self.assertEqual(found, ["plain"])


class ApplyCliTests(unittest.TestCase):
    def _make_workspace(self, tmp, dicts, files):
        i18n_dir = os.path.join(tmp, "i18n")
        zh_dir = os.path.join(i18n_dir, "zh-CN")
        os.makedirs(zh_dir)
        with open(os.path.join(HERE, "apply.py"), encoding="utf-8") as src_f:
            apply_src = src_f.read()
        apply_copy = os.path.join(i18n_dir, "apply.py")
        with open(apply_copy, "w", encoding="utf-8") as dst_f:
            dst_f.write(apply_src)
        for name, content in dicts.items():
            with open(os.path.join(zh_dir, name), "w", encoding="utf-8") as f:
                if isinstance(content, str):
                    f.write(content)
                else:
                    json.dump(content, f, ensure_ascii=False, indent=2)
        root = os.path.join(tmp, "repo")
        for rel, content in files.items():
            full = os.path.join(root, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)
        return apply_copy, root

    def _run(self, apply_copy, *args):
        return subprocess.run(
            [sys.executable, "-B", apply_copy, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_dry_run_does_not_modify_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = 'fn ui() -> &\'static str { "Hello" }\n'
            apply_copy, root = self._make_workspace(
                tmp,
                {"01.json": {"codex-rs/tui/src/ui.rs": {"Hello": "你好"}}},
                {"codex-rs/tui/src/ui.rs": original},
            )
            res = self._run(apply_copy, root, "--check", "--strict")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("共替换 1 处字符串, 0 条翻译未匹配", res.stdout)
            with open(os.path.join(root, "codex-rs/tui/src/ui.rs"), encoding="utf-8") as f:
                self.assertEqual(f.read(), original)

    def test_cross_file_duplicate_key_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            apply_copy, root = self._make_workspace(
                tmp,
                {
                    "01.json": {"codex-rs/tui/src/ui.rs": {"Hello": "你好"}},
                    "02.json": {"codex-rs/tui/src/ui.rs": {"Hello": "您好"}},
                },
                {"codex-rs/tui/src/ui.rs": 'fn ui() { let _ = "Hello"; }\n'},
            )
            res = self._run(apply_copy, root, "--check")
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("重复翻译键", res.stdout)

    def test_logic_position_skipped_unless_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = (
                'fn f(x: &str) -> &\'static str {\n'
                '    if x == "Working" { return "Working"; }\n'
                '    "Done"\n'
                '}\n'
            )
            apply_copy, root = self._make_workspace(
                tmp,
                {"01.json": {"codex-rs/tui/src/ui.rs": {"Working": "处理中", "Done": "完成"}}},
                {"codex-rs/tui/src/ui.rs": src},
            )
            res = self._run(apply_copy, root, "--strict")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("已跳过", res.stdout)
            with open(os.path.join(root, "codex-rs/tui/src/ui.rs"), encoding="utf-8") as f:
                patched = f.read()
            self.assertIn('if x == "Working"', patched)
            self.assertIn('"完成"', patched)

    def test_strict_fails_on_stale_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            apply_copy, root = self._make_workspace(
                tmp,
                {"01.json": {"codex-rs/tui/src/ui.rs": {"Missing": "缺失"}}},
                {"codex-rs/tui/src/ui.rs": 'fn ui() { let _ = "Other"; }\n'},
            )
            res = self._run(apply_copy, root, "--check", "--strict")
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("警告: 未找到原文", res.stdout)


if __name__ == "__main__":
    unittest.main()
