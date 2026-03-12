"""Multi-language chunker that combines AST and tree-sitter approaches."""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from chunking.code_chunk import CodeChunk
from chunking.tree_sitter import TreeSitterChunker, TreeSitterChunk
from chunking.languages import LANGUAGE_MAP
from chunking.structured_data_chunker import StructuredDataChunker, STRUCTURED_DATA_EXTENSION_MAP

logger = logging.getLogger(__name__)


class MultiLanguageChunker:
    """Unified chunker supporting multiple programming languages."""
    # Supported extensions - derived from LANGUAGE_MAP
    SUPPORTED_EXTENSIONS = set(LANGUAGE_MAP.keys()) | set(STRUCTURED_DATA_EXTENSION_MAP.keys())
    CONFIG_FILE_NAME = '.agent-context-code.json'
    # 100K lines — aligned with the 10 MB byte limit. A typical structured
    # config file averages ~100 bytes/line, so 10 MB ≈ 100K lines.
    DEFAULT_MAX_STRUCTURED_FILE_LINES = 100_000
    # 10 MB — covers large OpenAPI specs and monorepo configs while still
    # excluding truly huge generated files (package-lock.json, yarn.lock).
    # Override per-project via CODE_SEARCH_MAX_STRUCTURED_FILE_BYTES env var
    # or the max_file_bytes param on index_directory().
    DEFAULT_MAX_STRUCTURED_FILE_BYTES = 10_000_000
    
    # Common large/build/tooling directories to skip during traversal
    DEFAULT_IGNORED_DIRS = {
        '__pycache__', '.git', '.hg', '.svn',
        '.venv', 'venv', 'env', '.env', '.direnv',
        'node_modules', '.pnpm-store', '.yarn',
        '.pytest_cache', '.mypy_cache', '.ruff_cache', '.pytype', '.ipynb_checkpoints',
        'build', 'dist', 'out', 'public',
        '.next', '.nuxt', '.svelte-kit', '.angular', '.astro', '.vite',
        '.cache', '.parcel-cache', '.turbo',
        'coverage', '.coverage', '.nyc_output',
        '.gradle', '.idea', '.vscode', '.docusaurus', '.vercel', '.serverless', '.terraform', '.mvn', '.tox',
        'target', 'bin', 'obj'
    }
    
    def __init__(
        self,
        root_path: Optional[str] = None,
        max_structured_file_bytes: Optional[int] = None,
    ):
        """Initialize multi-language chunker.

        Args:
            root_path: Optional root path for relative path calculation
            max_structured_file_bytes: Optional override for the max
                structured file size limit (bytes).  When provided,
                takes precedence over the project config / env default.
        """
        self.root_path = root_path
        self.indexing_config = self._load_indexing_config()
        if max_structured_file_bytes is not None:
            self.indexing_config['max_structured_file_bytes'] = max_structured_file_bytes
        self.excluded_extensions = set(self.indexing_config['exclude_extensions'])
        self.supported_extensions = self.SUPPORTED_EXTENSIONS - self.excluded_extensions
        # Use tree-sitter for all programming languages and a structured parser for config files
        self.tree_sitter_chunker = TreeSitterChunker()
        self.structured_data_chunker = StructuredDataChunker(
            root_path=root_path,
            max_file_lines=self.indexing_config['max_structured_file_lines'],
            max_file_bytes=self.indexing_config['max_structured_file_bytes'],
        )

    def _load_indexing_config(self) -> dict:
        """Load per-project and environment indexing controls."""
        config = {}

        if self.root_path:
            config_path = Path(self.root_path) / self.CONFIG_FILE_NAME
            if config_path.is_file():
                try:
                    loaded = json.loads(config_path.read_text(encoding='utf-8'))
                    if isinstance(loaded, dict):
                        config = loaded
                    else:
                        logger.warning(
                            "Ignoring %s: expected a JSON object but got %s",
                            config_path,
                            type(loaded).__name__,
                        )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    logger.warning(f"Failed to load indexing config from {config_path}: {exc}")

        excluded_extensions = set()
        for extension in config.get('exclude_extensions', []):
            normalized = self._normalize_extension(extension)
            if normalized:
                excluded_extensions.add(normalized)

        env_excluded = os.getenv('CODE_SEARCH_EXCLUDE_EXTENSIONS', '')
        if env_excluded:
            for extension in env_excluded.split(','):
                normalized = self._normalize_extension(extension)
                if normalized:
                    excluded_extensions.add(normalized)

        return {
            'exclude_extensions': sorted(excluded_extensions),
            'max_structured_file_lines': self._read_positive_int(
                os.getenv('CODE_SEARCH_MAX_STRUCTURED_FILE_LINES'),
                config.get('max_structured_file_lines'),
                self.DEFAULT_MAX_STRUCTURED_FILE_LINES,
            ),
            'max_structured_file_bytes': self._read_positive_int(
                os.getenv('CODE_SEARCH_MAX_STRUCTURED_FILE_BYTES'),
                config.get('max_structured_file_bytes'),
                self.DEFAULT_MAX_STRUCTURED_FILE_BYTES,
            ),
        }

    def _normalize_extension(self, extension: str) -> Optional[str]:
        """Normalize configured file extensions."""
        if not extension:
            return None

        normalized = extension.strip().lower()
        if not normalized:
            return None
        if not normalized.startswith('.'):
            normalized = f'.{normalized}'
        return normalized

    def _read_positive_int(
        self,
        env_value: Optional[str],
        config_value: Optional[int | str],
        default: Optional[int],
    ) -> Optional[int]:
        """Read a positive integer from env/config; zero or blank disables the limit."""
        value = env_value if env_value not in (None, '') else config_value
        if value in (None, ''):
            return default

        try:
            parsed = int(value)
        except (TypeError, ValueError):
            logger.warning(f"Invalid indexing limit {value!r}; using default {default}")
            return default

        return parsed if parsed > 0 else None

    def _is_internal_config_file(self, file_path: str) -> bool:
        """Avoid indexing the local indexing configuration itself."""
        return Path(file_path).name == self.CONFIG_FILE_NAME

    @property
    def skipped_files(self) -> List:
        """Files skipped during chunking (size/line limits exceeded)."""
        return self.structured_data_chunker.skipped_files

    def reset_skipped_files(self) -> None:
        """Clear the skipped files list (call before each indexing session)."""
        self.structured_data_chunker.reset_skipped_files()

    def get_indexing_config_signature(self) -> dict:
        """Return the active indexing configuration for cache invalidation."""
        return dict(self.indexing_config)
    
    def is_supported(self, file_path: str) -> bool:
        """Check if file type is supported.
        
        Args:
            file_path: Path to file
            
        Returns:
            True if file type is supported
        """
        if self._is_internal_config_file(file_path):
            return False

        suffix = Path(file_path).suffix.lower()
        return suffix in self.supported_extensions
    
    def chunk_file(self, file_path: str) -> List[CodeChunk]:
        """Chunk a file into semantic units.
        
        Args:
            file_path: Path to the file
            
        Returns:
            List of CodeChunk objects
        """
        if not self.is_supported(file_path):
            logger.debug(f"File type not supported: {file_path}")
            return []

        # Use tree-sitter for programming languages and the structured parser for config files
        if Path(file_path).suffix.lower() in STRUCTURED_DATA_EXTENSION_MAP:
            return self.structured_data_chunker.chunk_file(file_path)

        tree_chunks = self.tree_sitter_chunker.chunk_file(file_path)
        # Convert TreeSitterChunk to CodeChunk
        return self._convert_tree_chunks(tree_chunks, file_path)
        # Let exceptions propagate — callers handle them and populate chunking_errors
    
    def _convert_tree_chunks(self, tree_chunks: List[TreeSitterChunk], file_path: str) -> List[CodeChunk]:
        """Convert tree-sitter chunks to CodeChunk format.
        
        Args:
            tree_chunks: List of TreeSitterChunk objects
            file_path: Path to the source file
            
        Returns:
            List of CodeChunk objects
        """
        code_chunks = []
        
        for tchunk in tree_chunks:
            # Extract metadata
            name = tchunk.metadata.get('name')
            docstring = tchunk.metadata.get('docstring')
            # 'annotations' carries Kotlin/JVM @Annotation names; fall back to
            # 'decorators' used by the Python AST chunker.
            decorators = tchunk.metadata.get('annotations', tchunk.metadata.get('decorators', []))
            
            # Map tree-sitter node types to our chunk types
            chunk_type_map = {
                'function_declaration': 'function',
                'function_definition': 'function',
                'arrow_function': 'function',
                'function': 'function',            # JS anonymous, Haskell
                'function_item': 'function',       # Rust
                'method_declaration': 'method',    # Go, Java, PHP
                'method_definition': 'method',
                'class_declaration': 'class',      # Java, C#, C++, Swift
                'class_definition': 'class',       # Python, Scala
                'class_specifier': 'class',        # C++
                'interface_declaration': 'interface',
                'type_alias_declaration': 'type',
                'type_declaration': 'type',        # Go
                'enum_declaration': 'enum',        # Java, C#, PHP
                'enum_specifier': 'enum',          # C
                'enum_item': 'enum',               # Rust
                'struct_declaration': 'struct',    # C#
                'struct_specifier': 'struct',      # C/C++
                'struct_item': 'struct',           # Rust
                'union_specifier': 'union',        # C/C++
                'namespace_definition': 'namespace',  # C++, PHP
                'namespace_declaration': 'namespace',  # C#
                'impl_item': 'impl',               # Rust
                'trait_item': 'trait',              # Rust
                'mod_item': 'module',              # Rust
                'macro_definition': 'macro',       # Rust
                'constructor_declaration': 'constructor',  # Java/C#
                'secondary_constructor': 'constructor',    # Kotlin
                'anonymous_initializer': 'init',   # Kotlin init { } blocks
                'destructor_declaration': 'destructor',    # C#
                'property_declaration': 'property',        # C#, Swift
                'object_declaration': 'object',    # Kotlin
                'companion_object': 'object',      # Kotlin
                'event_declaration': 'event',      # C#
                'template_declaration': 'template',  # C++
                'concept_definition': 'concept',   # C++
                'annotation_type_declaration': 'annotation',  # Java
                'script_element': 'script',        # Svelte
                'style_element': 'style',          # Svelte
                'section': 'section',              # Markdown
                'preamble': 'preamble',            # Markdown
                'document': 'document',            # Markdown
                # Java 16+
                'record_declaration': 'record',
                # Ruby
                'method': 'method',
                'singleton_method': 'method',
                'module': 'module',
                'class': 'class',                  # Ruby, Haskell type class
                # PHP
                'trait_declaration': 'trait',
                # Swift
                'protocol_declaration': 'protocol',
                'init_declaration': 'constructor',
                # CSS
                'rule_set': 'style_rule',
                'media_statement': 'media_query',
                'keyframes_statement': 'keyframes',
                'import_statement': 'import',
                'supports_statement': 'supports',
                'charset_statement': 'charset',
                # HTML (elements chunked via custom chunk_code)
                'element': 'element',
                # SQL
                'create_table': 'table',
                'create_view': 'view',
                'create_index': 'index',
                'create_function': 'function',
                'create_type': 'type',
                'create_trigger': 'trigger',
                # HCL/Terraform
                'block': 'block',
                # Scala
                'object_definition': 'object',
                'trait_definition': 'trait',
                'val_definition': 'property',
                'var_definition': 'property',
                'type_definition': 'type',
                # Lua — uses function_declaration (already mapped)
                # Elixir — uses 'call' with declaration_kind override
                'call': 'function',
                # Haskell
                'signature': 'signature',
                'data_type': 'type',
                'instance': 'instance',
                'type_synomym': 'type',
                'newtype': 'type',
            }
            
            chunk_type = chunk_type_map.get(tchunk.node_type, tchunk.node_type)
            declaration_kind = tchunk.metadata.get('declaration_kind')
            # Some grammars reuse a broad node type (for example Kotlin class_declaration)
            # and expose the more specific kind in metadata instead.
            if declaration_kind in {'interface', 'enum', 'object', 'property', 'init',
                                     'record', 'module', 'trait', 'protocol',
                                     'signature', 'instance', 'type', 'macro',
                                     'function', 'struct', 'impl'}:
                chunk_type = declaration_kind
            
            # Extract parent name and adjust chunk type for methods
            parent_name = tchunk.metadata.get('parent_name')
            
            # If we have a parent_name and it's a function, it's actually a method
            if parent_name and chunk_type == 'function':
                chunk_type = 'method'
            
            # Build folder structure and relative path from file path
            path = Path(file_path)
            folder_parts = []
            relative_path_str = str(path)
            if self.root_path:
                try:
                    rel_path = path.relative_to(self.root_path)
                    folder_parts = list(rel_path.parent.parts)
                    relative_path_str = str(rel_path).replace("\\", "/")
                except ValueError:
                    folder_parts = [path.parent.name] if path.parent.name else []
            else:
                folder_parts = [path.parent.name] if path.parent.name else []
            
            # Extract semantic tags from metadata
            tags = []
            if tchunk.metadata.get('is_async'):
                tags.append('async')
            if tchunk.metadata.get('is_generator'):
                tags.append('generator')
            if tchunk.metadata.get('is_export'):
                tags.append('export')
            if tchunk.metadata.get('has_generics'):
                tags.append('generic')
            if tchunk.metadata.get('is_component'):
                tags.append('component')
            if tchunk.metadata.get('is_extension'):
                tags.append('extension')
            
            # Add language tag
            tags.append(tchunk.language)
            
            # Create CodeChunk
            chunk = CodeChunk(
                file_path=str(path),
                relative_path=relative_path_str,
                folder_structure=folder_parts,
                chunk_type=chunk_type,
                content=tchunk.content,
                start_line=tchunk.start_line,
                end_line=tchunk.end_line,
                name=name,
                parent_name=parent_name,
                docstring=docstring,
                decorators=decorators,
                imports=[],  # Tree-sitter doesn't extract imports yet
                complexity_score=0,  # Not calculated for tree-sitter chunks
                tags=tags
            )
            
            code_chunks.append(chunk)
        
        return code_chunks
    
    def chunk_directory(self, directory_path: str, extensions: Optional[List[str]] = None) -> List[CodeChunk]:
        """Chunk all supported files in a directory.
        
        Args:
            directory_path: Path to directory
            extensions: Optional list of extensions to process (default: all supported)
            
        Returns:
            List of CodeChunk objects from all files
        """
        all_chunks = []
        dir_path = Path(directory_path)
        
        if not dir_path.exists() or not dir_path.is_dir():
            logger.error(f"Directory does not exist: {directory_path}")
            return []
        
        # Use provided extensions or all supported
        if extensions:
            valid_extensions = {
                normalized
                for ext in extensions
                if (normalized := self._normalize_extension(ext)) is not None
            } & self.supported_extensions
        else:
            valid_extensions = self.supported_extensions
        
        # Single-pass directory walk — one rglob("*") instead of N per-extension
        ignored = self.DEFAULT_IGNORED_DIRS
        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix not in valid_extensions:
                continue
            # Skip common large/build/tooling directories
            if any(part in ignored for part in file_path.parts):
                continue

            try:
                chunks = self.chunk_file(str(file_path))
                all_chunks.extend(chunks)
                logger.debug(f"Chunked {len(chunks)} from {file_path}")
            except Exception as e:
                logger.warning(f"Failed to chunk {file_path}: {e}")
        
        logger.info(f"Total chunks from directory: {len(all_chunks)}")
        return all_chunks
