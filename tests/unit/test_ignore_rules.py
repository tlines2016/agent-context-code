"""Unit tests for the IgnoreRules engine."""

import os
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase

from merkle.ignore_rules import IgnoreRules


class TestIgnoreRulesHardcoded(TestCase):
    """Hardcoded patterns work without any ignore files."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hardcoded_directory_patterns(self):
        rules = IgnoreRules(self.temp_dir)
        path = self.temp_dir / "__pycache__"
        assert rules.should_ignore(path, "__pycache__/")
        path = self.temp_dir / ".git"
        assert rules.should_ignore(path, ".git/")
        path = self.temp_dir / "node_modules"
        assert rules.should_ignore(path, "node_modules/")

    def test_hardcoded_file_patterns(self):
        rules = IgnoreRules(self.temp_dir)
        path = self.temp_dir / "foo.pyc"
        assert rules.should_ignore(path, "foo.pyc")
        path = self.temp_dir / ".DS_Store"
        assert rules.should_ignore(path, ".DS_Store")

    def test_non_ignored_file(self):
        rules = IgnoreRules(self.temp_dir)
        path = self.temp_dir / "main.py"
        assert not rules.should_ignore(path, "main.py")

    def test_stats_counter_accuracy(self):
        rules = IgnoreRules(self.temp_dir)
        rules.should_ignore(self.temp_dir / "__pycache__", "__pycache__/")
        rules.should_ignore(self.temp_dir / "main.py", "main.py")
        rules.should_ignore(self.temp_dir / "foo.pyc", "foo.pyc")
        stats = rules.get_stats()
        assert stats["ignored_by_hardcoded"] == 2
        assert stats["total_ignored"] == 2


class TestIgnoreRulesGitignore(TestCase):
    """Root .gitignore loaded and applied."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_gitignore_patterns(self):
        (self.temp_dir / ".gitignore").write_text("*.log\nsecrets/\n")
        rules = IgnoreRules(self.temp_dir)
        assert rules.should_ignore(self.temp_dir / "debug.log", "debug.log")
        assert rules.should_ignore(self.temp_dir / "secrets", "secrets/")
        assert not rules.should_ignore(self.temp_dir / "main.py", "main.py")
        stats = rules.get_stats()
        assert stats["ignored_by_gitignore"] == 2

    def test_gitignore_negation(self):
        (self.temp_dir / ".gitignore").write_text("*.log\n!important.log\n")
        rules = IgnoreRules(self.temp_dir)
        assert rules.should_ignore(self.temp_dir / "debug.log", "debug.log")
        assert not rules.should_ignore(self.temp_dir / "important.log", "important.log")


class TestIgnoreRulesCursorignore(TestCase):
    """Root .cursorignore loaded and applied."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cursorignore_patterns(self):
        (self.temp_dir / ".cursorignore").write_text("generated/\n*.gen.ts\n")
        rules = IgnoreRules(self.temp_dir)
        assert rules.should_ignore(self.temp_dir / "generated", "generated/")
        assert rules.should_ignore(self.temp_dir / "foo.gen.ts", "foo.gen.ts")
        assert not rules.should_ignore(self.temp_dir / "main.ts", "main.ts")
        stats = rules.get_stats()
        assert stats["ignored_by_cursorignore"] == 2


class TestIgnoreRulesNested(TestCase):
    """Nested per-directory .gitignore rules."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_nested_gitignore(self):
        sub = self.temp_dir / "sub"
        sub.mkdir()
        (sub / ".gitignore").write_text("*.tmp\n")

        rules = IgnoreRules(self.temp_dir)
        rules.enter_directory(sub)

        # File inside sub/ should match nested rule
        assert rules.should_ignore(sub / "data.tmp", "sub/data.tmp")
        # File at root should NOT match nested rule
        assert not rules.should_ignore(self.temp_dir / "data.tmp", "data.tmp")

        rules.leave_directory(sub)

    def test_nested_scope_popped(self):
        sub = self.temp_dir / "sub"
        sub.mkdir()
        (sub / ".gitignore").write_text("*.tmp\n")

        rules = IgnoreRules(self.temp_dir)
        rules.enter_directory(sub)
        rules.leave_directory(sub)

        # After leaving, nested rule should no longer apply
        assert not rules.should_ignore(sub / "data.tmp", "sub/data.tmp")


class TestIgnoreRulesSignature(TestCase):
    """Signature changes when ignore file content changes."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_signature_changes(self):
        sig1 = IgnoreRules.compute_signature(self.temp_dir)
        assert sig1["gitignore_hash"] is None

        (self.temp_dir / ".gitignore").write_text("*.log\n")
        sig2 = IgnoreRules.compute_signature(self.temp_dir)
        assert sig2["gitignore_hash"] is not None

        (self.temp_dir / ".gitignore").write_text("*.log\n*.tmp\n")
        sig3 = IgnoreRules.compute_signature(self.temp_dir)
        assert sig3["gitignore_hash"] != sig2["gitignore_hash"]

    def test_instance_signature_matches_static(self):
        (self.temp_dir / ".gitignore").write_text("*.log\n")
        rules = IgnoreRules(self.temp_dir)
        assert rules.get_ignore_signature() == IgnoreRules.compute_signature(self.temp_dir)


class TestIgnoreRulesMissing(TestCase):
    """Missing ignore files — hardcoded still works, no errors."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_no_ignore_files(self):
        rules = IgnoreRules(self.temp_dir)
        # Hardcoded still works
        assert rules.should_ignore(self.temp_dir / ".git", ".git/")
        # Non-ignored still passes
        assert not rules.should_ignore(self.temp_dir / "main.py", "main.py")
