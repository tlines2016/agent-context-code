"""Base classes and data structures for tree-sitter based code chunking."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from tree_sitter import Parser

from chunking.available_languages import get_available_language
# map {language: language_obj}
AVAILABLE_LANGUAGES = get_available_language()

logger = logging.getLogger(__name__)


@dataclass
class TreeSitterChunk:
    """Represents a code chunk extracted using tree-sitter."""

    content: str
    start_line: int
    end_line: int
    node_type: str
    language: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict:
        """Convert to dictionary format compatible with existing system."""
        return {
            'content': self.content,
            'start_line': self.start_line,
            'end_line': self.end_line,
            'type': self.node_type,
            'language': self.language,
            'metadata': self.metadata
        }



# Node types that act as containers whose children should also be traversed
# for individual sub-chunks (methods, nested functions, etc.).  Extending
# this set is the primary way to add cross-language container support.
_CONTAINER_NODE_TYPES: frozenset[str] = frozenset({
    # Class-like containers (all languages)
    'class_definition',       # Python, Scala
    'class_declaration',      # Java, C#, C++, Swift (class/struct/enum/extension)
    'object_declaration',     # Kotlin (singleton)
    'companion_object',       # Kotlin companion object
    # Interface & enum containers (members can have methods)
    'interface_declaration',  # Java, C#, Go, PHP
    'enum_declaration',       # Java, C#, PHP (enums may contain methods)
    'struct_declaration',     # C#, Go
    # Rust-specific containers
    'impl_item',              # impl blocks with associated functions/methods
    'trait_item',             # trait definitions with method signatures/defaults
    # C# namespaces (can contain nested types with their own methods)
    'namespace_declaration',
    # Java 16+ records (can contain methods)
    'record_declaration',
    # Ruby containers
    'module',                 # Ruby modules (contain classes & methods)
    'class',                  # Ruby classes, Haskell type classes
    # PHP containers
    'trait_declaration',      # PHP traits (contain methods)
    'namespace_definition',   # PHP namespaces (contain classes)
    # Swift containers
    'protocol_declaration',   # Swift protocols (contain method signatures)
    # Scala containers
    'object_definition',      # Scala objects (contain methods)
    'trait_definition',       # Scala traits (contain methods)
    # Haskell containers
    'instance',               # Haskell instance declarations (contain method implementations)
})


class LanguageChunker(ABC):
    """Abstract base class for language-specific chunkers."""

    def __init__(self, language_name: str):
        """Initialize language chunker.

        Args:
            language_name: Programming language name
        """
        self.language_name = language_name
        if language_name not in AVAILABLE_LANGUAGES:
            raise ValueError(f"Language {language_name} not available. Install tree-sitter-{language_name}")

        self.language = AVAILABLE_LANGUAGES[language_name]
        self.parser = Parser(self.language)
        self.splittable_node_types = self._get_splittable_node_types()

    @abstractmethod
    def _get_splittable_node_types(self) -> Set[str]:
        """Get node types that should be split into chunks.

        Returns:
            Set of node type names
        """
        pass

    @abstractmethod
    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract metadata from a node.

        Args:
            node: Tree-sitter node
            source: Source code bytes

        Returns:
            Metadata dictionary
        """
        pass

    def should_chunk_node(self, node: Any) -> bool:
        """Check if a node should be chunked.

        Args:
            node: Tree-sitter node

        Returns:
            True if node should be chunked
        """
        if node.type not in self.splittable_node_types:
            return False
        # Guard against keyword tokens that share their type name with
        # declaration nodes (e.g. Ruby's `class` keyword vs `class` declaration,
        # Haskell's `class` keyword vs type-class declaration).  Leaf nodes
        # (zero children) are always keywords/punctuation, never meaningful
        # code constructs worth chunking.
        if node.child_count == 0:
            return False
        return True

    def get_node_text(self, node: Any, source: bytes) -> str:
        """Get text content of a node.

        Args:
            node: Tree-sitter node
            source: Source code bytes

        Returns:
            Text content
        """
        return source[node.start_byte:node.end_byte].decode('utf-8')

    def get_line_numbers(self, node: Any) -> Tuple[int, int]:
        """Get start and end line numbers for a node.

        Args:
            node: Tree-sitter node

        Returns:
            Tuple of (start_line, end_line)
        """
        # Tree-sitter uses 0-based indexing, convert to 1-based
        return node.start_point[0] + 1, node.end_point[0] + 1

    def chunk_code(self, source_code: str) -> List[TreeSitterChunk]:
        """Chunk source code into semantic units.

        Args:
            source_code: Source code string

        Returns:
            List of TreeSitterChunk objects
        """
        source_bytes = bytes(source_code, 'utf-8')
        tree = self.parser.parse(source_bytes)
        chunks = []

        def traverse(node, depth=0, parent_info=None):
            """Recursively traverse the tree and extract chunks."""
            if self.should_chunk_node(node):
                start_line, end_line = self.get_line_numbers(node)
                content = self.get_node_text(node, source_bytes)
                metadata = self.extract_metadata(node, source_bytes)

                # Add parent information if available
                if parent_info:
                    metadata.update(parent_info)

                chunk = TreeSitterChunk(
                    content=content,
                    start_line=start_line,
                    end_line=end_line,
                    node_type=node.type,
                    language=self.language_name,
                    metadata=metadata
                )
                chunks.append(chunk)

                # For container nodes, continue traversing to find nested members.
                # _CONTAINER_NODE_TYPES covers classes, interfaces, enums,
                # Rust impl/trait blocks, and C# namespaces.
                if node.type in _CONTAINER_NODE_TYPES:
                    parent_type = metadata.get('declaration_kind', 'class')
                    container_info = {
                        'parent_name': metadata.get('name'),
                        'parent_type': parent_type
                    }
                    for child in node.children:
                        traverse(child, depth + 1, container_info)
                return

            # Traverse children, passing along parent info
            for child in node.children:
                traverse(child, depth + 1, parent_info)

        traverse(tree.root_node)

        # If no chunks found, create a single module-level chunk
        if not chunks and source_code.strip():
            chunks.append(TreeSitterChunk(
                content=source_code,
                start_line=1,
                end_line=len(source_code.split('\n')),
                node_type='module',
                language=self.language_name,
                metadata={'type': 'module'}
            ))

        return chunks
