"""Unit tests for MerkleDAG class."""

import os
import tempfile
import shutil
from pathlib import Path
from unittest import TestCase

from merkle.merkle_dag import MerkleDAG


def _normalize_paths(paths):
    """Normalize a list of paths to use forward slashes for cross-platform comparison."""
    return [p.replace(os.sep, '/') for p in paths]


class TestMerkleDAG(TestCase):
    """Test MerkleDAG class."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_path = Path(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_test_files(self):
        """Create test file structure."""
        # Create directories
        (self.test_path / 'src').mkdir()
        (self.test_path / 'tests').mkdir()

        # Create files
        (self.test_path / 'README.md').write_text('# Test Project')
        (self.test_path / 'src' / 'main.py').write_text('def main(): pass')
        (self.test_path / 'src' / 'utils.py').write_text('def helper(): pass')
        (self.test_path / 'tests' / 'test_main.py').write_text('def test_main(): pass')

    def test_dag_building(self):
        """Test building a Merkle DAG from directory."""
        self.create_test_files()

        dag = MerkleDAG(self.temp_dir)
        dag.build()

        # Check root node exists
        assert dag.root_node is not None
        assert dag.root_node.is_file is False

        # Check files are tracked
        all_files = dag.get_all_files()
        assert len(all_files) == 4

        # Normalize paths for cross-platform comparison (Windows uses backslashes)
        normalized = _normalize_paths(all_files)
        assert 'README.md' in normalized
        assert 'src/main.py' in normalized
        assert 'src/utils.py' in normalized
        assert 'tests/test_main.py' in normalized

    def test_file_hashing(self):
        """Test file hash calculation."""
        self.create_test_files()

        dag = MerkleDAG(self.temp_dir)
        dag.build()

        file_hashes = dag.get_file_hashes()

        # All files should have hashes
        assert len(file_hashes) == 4

        # Hashes should be consistent
        dag2 = MerkleDAG(self.temp_dir)
        dag2.build()
        file_hashes2 = dag2.get_file_hashes()

        assert file_hashes == file_hashes2

    def test_directory_hashing(self):
        """Test directory hash changes with content."""
        self.create_test_files()

        dag1 = MerkleDAG(self.temp_dir)
        dag1.build()
        root_hash1 = dag1.get_root_hash()

        # Modify a file
        (self.test_path / 'src' / 'main.py').write_text('def main(): return 1')

        dag2 = MerkleDAG(self.temp_dir)
        dag2.build()
        root_hash2 = dag2.get_root_hash()

        # Root hash should change
        assert root_hash1 != root_hash2

        # Src directory hash should change
        src_node1 = dag1.find_node('src')
        src_node2 = dag2.find_node('src')
        assert src_node1.hash != src_node2.hash

        # Tests directory hash should remain same
        tests_node1 = dag1.find_node('tests')
        tests_node2 = dag2.find_node('tests')
        assert tests_node1.hash == tests_node2.hash

    def test_ignore_patterns(self):
        """Test ignore patterns in DAG building."""
        self.create_test_files()

        # Create files that should be ignored
        (self.test_path / '.git').mkdir()
        (self.test_path / '.git' / 'config').write_text('config')
        (self.test_path / '__pycache__').mkdir()
        (self.test_path / '__pycache__' / 'cache.pyc').write_text('cache')
        (self.test_path / 'test.pyc').write_text('pyc')

        dag = MerkleDAG(self.temp_dir)
        dag.build()

        all_files = dag.get_all_files()
        normalized = _normalize_paths(all_files)

        # Ignored files should not be in DAG
        assert '.git/config' not in normalized
        assert '__pycache__/cache.pyc' not in normalized
        assert 'test.pyc' not in normalized

        # Regular files should be present
        assert 'README.md' in normalized

    def test_gitignore_respected(self):
        """Test that .gitignore rules are respected during DAG building."""
        self.create_test_files()

        # Create a .gitignore that excludes *.log files
        (self.test_path / '.gitignore').write_text('*.log\n')

        # Create a log file that should be excluded
        (self.test_path / 'debug.log').write_text('debug output')

        dag = MerkleDAG(self.temp_dir)
        dag.build()

        all_files = dag.get_all_files()
        normalized = _normalize_paths(all_files)

        # debug.log should be excluded by .gitignore
        assert 'debug.log' not in normalized

        # Regular files should still be present
        assert 'src/main.py' in normalized

        # .gitignore itself should be included (it's a tracked file)
        assert '.gitignore' in normalized

        # Ignore stats should reflect the exclusion
        stats = dag.get_ignore_stats()
        assert stats['ignored_by_gitignore'] >= 1

    def test_cursorignore_respected(self):
        """Test that .cursorignore rules are respected during DAG building."""
        self.create_test_files()

        (self.test_path / '.cursorignore').write_text('tests/\n')

        dag = MerkleDAG(self.temp_dir)
        dag.build()

        all_files = dag.get_all_files()
        normalized = _normalize_paths(all_files)

        # tests/ dir should be excluded by .cursorignore
        assert 'tests/test_main.py' not in normalized

        # Other files should still be present
        assert 'src/main.py' in normalized

    def test_dag_serialization(self):
        """Test DAG to/from dict conversion."""
        self.create_test_files()

        dag1 = MerkleDAG(self.temp_dir)
        dag1.build()

        # Serialize
        data = dag1.to_dict()

        # Verify structure
        assert data['root_path'] == str(self.test_path)
        assert data['root_node'] is not None
        assert data['file_count'] == 4
        assert data['total_size'] > 0

        # Deserialize
        dag2 = MerkleDAG.from_dict(data)

        # Verify restoration
        assert dag2.root_path == dag1.root_path
        assert dag2.get_root_hash() == dag1.get_root_hash()
        assert dag2.get_all_files() == dag1.get_all_files()
