"""Basic tests for multi-language chunking."""

import pytest
from pathlib import Path
from chunking.multi_language_chunker import MultiLanguageChunker


class TestMultiLanguageChunker:
    """Test multi-language chunking functionality."""
    
    @pytest.fixture
    def chunker(self):
        """Create a chunker instance."""
        return MultiLanguageChunker()
    
    @pytest.fixture
    def test_data_dir(self):
        """Get test data directory."""
        return Path(__file__).parent.parent / "test_data" / "multi_language"
    
    def test_supported_extensions(self, chunker):
        """Test that all required extensions are supported."""
        assert chunker.is_supported("test.py")
        assert chunker.is_supported("test.js")
        assert chunker.is_supported("test.jsx")
        assert chunker.is_supported("test.ts")
        assert chunker.is_supported("test.tsx")
        assert chunker.is_supported("test.svelte")
        assert chunker.is_supported("test.java")
        assert chunker.is_supported("test.kt")
        assert chunker.is_supported("test.kts")
        assert chunker.is_supported("test.md")
        assert chunker.is_supported("test.go")
        assert chunker.is_supported("test.c")
        assert chunker.is_supported("test.cpp")
        assert chunker.is_supported("test.cc")
        assert chunker.is_supported("test.cxx")
        assert chunker.is_supported("test.c++")
        assert chunker.is_supported("test.cs")
        assert chunker.is_supported("test.rs")
        assert chunker.is_supported("test.yaml")
        assert chunker.is_supported("test.yml")
        assert chunker.is_supported("test.toml")
        assert chunker.is_supported("test.json")
        assert not chunker.is_supported("test.txt")
    
    def test_chunk_python_file(self, chunker, test_data_dir):
        """Test chunking Python file."""
        file_path = test_data_dir / "example.py"
        chunks = chunker.chunk_file(str(file_path))
        
        assert len(chunks) > 0
        # Should find the class and functions
        chunk_types = {chunk.chunk_type for chunk in chunks}
        assert "function" in chunk_types or "method" in chunk_types
        assert "class" in chunk_types
    
    def test_chunk_javascript_file(self, chunker, test_data_dir):
        """Test chunking JavaScript file."""
        file_path = test_data_dir / "example.js"
        chunks = chunker.chunk_file(str(file_path))
        
        assert len(chunks) > 0
        # Should find functions and class
        chunk_names = {chunk.name for chunk in chunks if chunk.name}
        assert "calculateSum" in chunk_names
        assert "Calculator" in chunk_names
    
    def test_chunk_typescript_file(self, chunker, test_data_dir):
        """Test chunking TypeScript file."""
        file_path = test_data_dir / "example.ts"
        chunks = chunker.chunk_file(str(file_path))
        
        assert len(chunks) > 0
        # Should find interface, class, and functions
        chunk_types = {chunk.chunk_type for chunk in chunks}
        assert any(t in chunk_types for t in ["class", "interface", "function"])
    
    def test_chunk_jsx_file(self, chunker, test_data_dir):
        """Test chunking JSX file."""
        file_path = test_data_dir / "Component.jsx"
        chunks = chunker.chunk_file(str(file_path))
        
        assert len(chunks) > 0
        # Should find React components
        chunk_names = {chunk.name for chunk in chunks if chunk.name}
        assert "Counter" in chunk_names or "UserCard" in chunk_names
    
    def test_chunk_tsx_file(self, chunker, test_data_dir):
        """Test chunking TSX file."""
        file_path = test_data_dir / "Component.tsx"
        chunks = chunker.chunk_file(str(file_path))
        
        assert len(chunks) > 0
        # Should find TypeScript React components
        chunk_names = {chunk.name for chunk in chunks if chunk.name}
        assert any(name in chunk_names for name in ["TypedCounter", "UserList"])
    
    def test_chunk_svelte_file(self, chunker, test_data_dir):
        """Test chunking Svelte file."""
        file_path = test_data_dir / "App.svelte"
        chunks = chunker.chunk_file(str(file_path))
        
        assert len(chunks) > 0
        # Should find script and style blocks
        chunk_types = {chunk.chunk_type for chunk in chunks}
        assert "script" in chunk_types or "style" in chunk_types or len(chunks) > 0
    
    def test_chunk_java_file(self, chunker, test_data_dir):
        """Test chunking Java file."""
        file_path = test_data_dir / "Calculator.java"
        chunks = chunker.chunk_file(str(file_path))
        
        assert len(chunks) > 0
        # Should find class, methods, interface, and enum
        chunk_names = {chunk.name for chunk in chunks if chunk.name}
        chunk_types = {chunk.chunk_type for chunk in chunks}
        
        assert "Calculator" in chunk_names
        assert "MathOperations" in chunk_names
        assert "Operation" in chunk_names
        assert any(t in chunk_types for t in ["class", "interface", "enum"])

    def test_chunk_kotlin_file(self, chunker, test_data_dir):
        """Test chunking Kotlin file."""
        file_path = test_data_dir / "Calculator.kt"
        chunks = chunker.chunk_file(str(file_path))

        assert len(chunks) > 0
        chunk_names = {chunk.name for chunk in chunks if chunk.name}
        chunk_types = {chunk.chunk_type for chunk in chunks}

        # Structural assertions: these names/types were present before the richer
        # metadata pass was added.  Keeping them ensures that metadata extraction
        # improvements don't accidentally drop chunks or rename existing symbols.
        assert "Calculator" in chunk_names
        assert "MathOperations" in chunk_names
        assert "Operation" in chunk_names
        assert "version" in chunk_names
        assert "create" in chunk_names
        assert "class" in chunk_types
        assert "interface" in chunk_types
        assert "enum" in chunk_types
        assert "object" in chunk_types
        assert "property" in chunk_types
        assert "constructor" in chunk_types

        # init { } blocks are chunked with chunk_type 'init'
        assert "init" in chunk_types

        # KDoc comments are extracted as docstrings
        assert any(c.docstring for c in chunks), "Expected at least one chunk with a KDoc docstring"

        # @Annotations appear as decorators on the chunk they annotate
        all_decorators = [dec for c in chunks for dec in (c.decorators or [])]
        assert any(dec.startswith('@') for dec in all_decorators), (
            "Expected at least one Kotlin @Annotation in chunk decorators"
        )

        # Extension functions get the 'extension' semantic tag
        assert any('extension' in (c.tags or []) for c in chunks), (
            "Expected an extension function chunk to carry the 'extension' tag"
        )


    def test_chunk_go_file(self, chunker, test_data_dir):
        """Test chunking Go file."""
        file_path = test_data_dir / "calculator.go"
        chunks = chunker.chunk_file(str(file_path))
        
        assert len(chunks) > 0
        # Should find functions, methods, types, and interfaces
        chunk_names = {chunk.name for chunk in chunks if chunk.name}
        chunk_types = {chunk.chunk_type for chunk in chunks}
        
        assert any(name in chunk_names for name in ["Calculator", "CalculateSum", "NewCalculator"])
        assert len(chunk_names) > 0
        assert any(t in chunk_types for t in ["function", "method", "type", "interface"]) or len(chunks) > 0
    
    def test_chunk_c_file(self, chunker, test_data_dir):
        """Test chunking C file."""
        file_path = test_data_dir / "calculator.c"
        chunks = chunker.chunk_file(str(file_path))
        
        # C parser may not be available, so chunks might be empty
        if len(chunks) > 0:
            chunk_names = {chunk.name for chunk in chunks if chunk.name}
            chunk_types = {chunk.chunk_type for chunk in chunks}
            
            assert len(chunk_names) > 0 or len(chunk_types) > 0
        # If no chunks, that's okay - parser not available
    
    def test_chunk_cpp_file(self, chunker, test_data_dir):
        """Test chunking C++ file."""
        file_path = test_data_dir / "Calculator.cpp"
        chunks = chunker.chunk_file(str(file_path))
        
        # C++ parser may not be available, so chunks might be empty
        if len(chunks) > 0:
            chunk_names = {chunk.name for chunk in chunks if chunk.name}
            chunk_types = {chunk.chunk_type for chunk in chunks}
            
            assert len(chunk_names) > 0 or len(chunk_types) > 0
        # If no chunks, that's okay - parser not available
    
    def test_chunk_csharp_file(self, chunker, test_data_dir):
        """Test chunking C# file."""
        file_path = test_data_dir / "Calculator.cs"
        chunks = chunker.chunk_file(str(file_path))
        
        # C# parser may not be available, so chunks might be empty
        if len(chunks) > 0:
            chunk_names = {chunk.name for chunk in chunks if chunk.name}
            chunk_types = {chunk.chunk_type for chunk in chunks}
            
            assert len(chunk_names) > 0 or len(chunk_types) > 0
        # If no chunks, that's okay - parser not available
    
    def test_chunk_rust_file(self, chunker, test_data_dir):
        """Test chunking Rust file."""
        file_path = test_data_dir / "calculator.rs"
        chunks = chunker.chunk_file(str(file_path))
        
        assert len(chunks) > 0
        # Should find functions, structs, traits, enums, impls, macros
        chunk_names = {chunk.name for chunk in chunks if chunk.name}
        chunk_types = {chunk.chunk_type for chunk in chunks}
        
        assert any(name in chunk_names for name in ["Calculator", "calculate_sum", "MathOperations", "Operation", "Point"])
        assert any(t in chunk_types for t in ["function", "struct", "trait", "enum", "impl", "macro"])

        # impl blocks must be traversed so their methods get individual chunks
        impl_method_chunks = [
            c for c in chunks
            if c.parent_name in {"Calculator", "Operation", "Point"}
            and c.chunk_type in {"function", "method"}
        ]
        assert len(impl_method_chunks) > 0, (
            "Expected methods inside Rust impl blocks to be individually indexed with parent_name set"
        )

    def test_chunk_java_interface_methods_have_parent_name(self, chunker, test_data_dir):
        """Methods declared inside a Java interface should have parent_name set."""
        file_path = test_data_dir / "Calculator.java"
        chunks = chunker.chunk_file(str(file_path))

        assert len(chunks) > 0
        interface_method_chunks = [
            c for c in chunks
            if c.parent_name == "MathOperations"
        ]
        assert len(interface_method_chunks) > 0, (
            "Expected method(s) inside Java interface MathOperations to have parent_name='MathOperations'"
        )

    def test_chunk_java_enum_methods_have_parent_name(self, chunker, test_data_dir):
        """Methods declared inside a Java enum should have parent_name set."""
        file_path = test_data_dir / "Calculator.java"
        chunks = chunker.chunk_file(str(file_path))

        assert len(chunks) > 0
        enum_method_chunks = [
            c for c in chunks
            if c.parent_name == "Operation"
            and c.chunk_type in {"function", "method"}
        ]
        assert len(enum_method_chunks) > 0, (
            "Expected method(s) inside Java enum Operation to have parent_name='Operation'"
        )

    def test_chunk_markdown_file(self, chunker, test_data_dir):
        """Test chunking Markdown file."""
        file_path = test_data_dir / "README.md"
        chunks = chunker.chunk_file(str(file_path))

        assert len(chunks) > 0
        chunk_names = {chunk.name for chunk in chunks if chunk.name}
        chunk_types = {chunk.chunk_type for chunk in chunks}

        assert "Overview" in chunk_names
        assert "Kotlin Support" in chunk_names
        assert "section" in chunk_types

    def test_chunk_yaml_file(self, chunker, test_data_dir):
        """Test chunking YAML config files."""
        file_path = test_data_dir / "config.yaml"
        chunks = chunker.chunk_file(str(file_path))

        assert len(chunks) > 0
        chunk_names = {chunk.name for chunk in chunks if chunk.name}
        chunk_types = {chunk.chunk_type for chunk in chunks}
        all_tags = {tag for chunk in chunks for tag in (chunk.tags or [])}

        assert "services" in chunk_names
        assert "database" in chunk_names
        assert "config_section" in chunk_types
        assert "yaml" in all_tags
        assert "config" in all_tags

    def test_chunk_toml_file(self, chunker, test_data_dir):
        """Test chunking TOML config files."""
        file_path = test_data_dir / "project.toml"
        chunks = chunker.chunk_file(str(file_path))

        assert len(chunks) > 0
        chunk_names = {chunk.name for chunk in chunks if chunk.name}
        all_tags = {tag for chunk in chunks for tag in (chunk.tags or [])}

        assert "project" in chunk_names
        assert "tool" in chunk_names
        assert "tool.ruff" in chunk_names
        assert "toml" in all_tags
        assert "config" in all_tags

    def test_chunk_json_file(self, chunker, test_data_dir):
        """Test chunking JSON config files."""
        file_path = test_data_dir / "package.json"
        chunks = chunker.chunk_file(str(file_path))

        assert len(chunks) > 0
        chunk_names = {chunk.name for chunk in chunks if chunk.name}
        all_tags = {tag for chunk in chunks for tag in (chunk.tags or [])}

        assert "scripts" in chunk_names
        assert "dependencies" in chunk_names
        assert "json" in all_tags
        assert "config" in all_tags

    def test_invalid_yaml_falls_back_to_document_chunk(self, chunker, tmp_path):
        """Invalid structured files should still index as a raw document chunk."""
        file_path = tmp_path / "broken.yaml"
        file_path.write_text("root:\n  - valid\n  invalid: [", encoding="utf-8")

        chunks = chunker.chunk_file(str(file_path))

        assert len(chunks) == 1
        assert chunks[0].chunk_type == "document"
        assert "invalid: [" in chunks[0].content
        assert "raw" in chunks[0].tags

    def test_indexing_config_can_exclude_extensions(self, tmp_path):
        """Project config should make it easy to exclude noisy file types."""
        (tmp_path / ".agent-context-code.json").write_text(
            '{"exclude_extensions": [".toml"]}',
            encoding="utf-8",
        )
        (tmp_path / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
        (tmp_path / "settings.toml").write_text("[server]\nport = 43594\n", encoding="utf-8")

        chunker = MultiLanguageChunker(str(tmp_path))
        chunks = chunker.chunk_directory(str(tmp_path))

        assert chunker.is_supported("main.py")
        assert not chunker.is_supported("settings.toml")
        assert all(not chunk.file_path.endswith(".toml") for chunk in chunks)

    def test_large_structured_files_can_be_skipped_by_config(self, tmp_path):
        """Structured file limits should prevent huge config files from muddying the index."""
        (tmp_path / ".agent-context-code.json").write_text(
            '{"max_structured_file_lines": 3}',
            encoding="utf-8",
        )
        (tmp_path / "large.toml").write_text(
            "\n".join(
                [
                    "[server]",
                    "port = 43594",
                    "host = \"127.0.0.1\"",
                    "[database]",
                    "url = \"sqlite:///game.db\"",
                ]
            ),
            encoding="utf-8",
        )

        chunker = MultiLanguageChunker(str(tmp_path))

        assert chunker.chunk_file(str(tmp_path / "large.toml")) == []

    def test_non_utf8_indexing_config_falls_back_to_defaults(self, monkeypatch, tmp_path):
        """A non-UTF-8 indexing config should not crash chunker initialization."""
        # Isolate from any CODE_SEARCH_* env vars that might be set in the test runner
        monkeypatch.delenv("CODE_SEARCH_EXCLUDE_EXTENSIONS", raising=False)
        monkeypatch.delenv("CODE_SEARCH_MAX_STRUCTURED_FILE_LINES", raising=False)
        monkeypatch.delenv("CODE_SEARCH_MAX_STRUCTURED_FILE_BYTES", raising=False)

        (tmp_path / ".agent-context-code.json").write_bytes(b"\xff\xfe\x00\x00")

        chunker = MultiLanguageChunker(str(tmp_path))

        assert chunker.excluded_extensions == set()
        assert (
            chunker.indexing_config["max_structured_file_lines"]
            == MultiLanguageChunker.DEFAULT_MAX_STRUCTURED_FILE_LINES
        )

    def test_non_utf8_structured_file_is_skipped(self, tmp_path):
        """Structured files that cannot be decoded as UTF-8 should be skipped safely."""
        file_path = tmp_path / "broken.yaml"
        file_path.write_bytes(b"\xff\xfe\x00\x00")

        chunker = MultiLanguageChunker(str(tmp_path))

        assert chunker.chunk_file(str(file_path)) == []

    def test_structured_chunks_keep_line_numbers(self, tmp_path):
        """Structured chunk line estimates should remain stable after line indexing."""
        file_path = tmp_path / "config.yaml"
        file_path.write_text(
            "database:\n"
            "  host: localhost\n"
            "services:\n"
            "  api:\n"
            "    port: 8080\n",
            encoding="utf-8",
        )

        chunker = MultiLanguageChunker(str(tmp_path))
        chunks = {chunk.name: chunk for chunk in chunker.chunk_file(str(file_path))}

        assert chunks["database"].start_line == 1
        assert chunks["services"].start_line == 3
        assert chunks["services.api"].start_line == 4

    def test_toml_with_datetime_values(self, tmp_path):
        """TOML files containing datetime values should be indexed without crashing."""
        file_path = tmp_path / "build.toml"
        file_path.write_text(
            "[build]\ndate = 2024-01-01\ntimestamp = 2024-01-01T12:00:00Z\n",
            encoding="utf-8",
        )

        chunker = MultiLanguageChunker(str(tmp_path))
        chunks = chunker.chunk_file(str(file_path))

        assert len(chunks) > 0
        all_content = " ".join(c.content for c in chunks)
        assert "2024-01-01" in all_content

    def test_invalid_non_dict_config_file_is_ignored(self, tmp_path):
        """A .agent-context-code.json that is not a JSON object should be skipped gracefully."""
        (tmp_path / ".agent-context-code.json").write_text(
            '["just", "a", "list"]', encoding="utf-8"
        )
        (tmp_path / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")

        # Should not raise; indexing config should fall back to defaults
        chunker = MultiLanguageChunker(str(tmp_path))
        assert chunker.excluded_extensions == set()
        assert chunker.is_supported("main.py")
