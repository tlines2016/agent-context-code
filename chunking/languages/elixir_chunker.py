"""Elixir-specific tree-sitter based chunker."""

from typing import Any, Dict, List, Set

from chunking.base_chunker import LanguageChunker, TreeSitterChunk


class ElixirChunker(LanguageChunker):
    """Elixir-specific chunker using tree-sitter.

    Elixir's tree-sitter grammar represents all definitions as 'call' nodes.
    The first child identifier determines the type (defmodule, def, defp, etc.).
    """

    # Call identifiers that represent meaningful definitions
    _DEF_KEYWORDS = frozenset({
        'defmodule', 'def', 'defp', 'defmacro', 'defmacrop',
        'defprotocol', 'defimpl', 'defguard', 'defguardp',
        'defdelegate', 'defstruct', 'defexception',
    })

    def __init__(self):
        super().__init__('elixir')

    def _get_splittable_node_types(self) -> Set[str]:
        """Not used directly — should_chunk_node is overridden."""
        return set()

    def should_chunk_node(self, node: Any) -> bool:
        """Check if a call node represents a definition."""
        if node.type != 'call':
            return False
        for child in node.children:
            if child.type == 'identifier':
                return child.text.decode('utf-8') in self._DEF_KEYWORDS
        return False

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract Elixir-specific metadata."""
        metadata = {'node_type': node.type}

        # Determine the definition type from the identifier
        def_type = None
        for child in node.children:
            if child.type == 'identifier':
                def_type = self.get_node_text(child, source)
                break

        if def_type:
            metadata['def_type'] = def_type

        # Map def types to declaration_kind for chunk_type resolution
        kind_map = {
            'defmodule': 'module',
            'def': 'function',
            'defp': 'function',
            'defmacro': 'macro',
            'defmacrop': 'macro',
            'defprotocol': 'protocol',
            'defimpl': 'impl',
            'defguard': 'function',
            'defguardp': 'function',
            'defdelegate': 'function',
            'defstruct': 'struct',
            'defexception': 'struct',
        }
        metadata['declaration_kind'] = kind_map.get(def_type, 'function')

        # Private definitions
        if def_type in ('defp', 'defmacrop', 'defguardp'):
            metadata['is_private'] = True

        # Extract name from arguments
        for child in node.children:
            if child.type == 'arguments':
                for arg in child.children:
                    if arg.type == 'alias':
                        # Module name (e.g., Calculator in defmodule Calculator)
                        metadata['name'] = self.get_node_text(arg, source)
                        break
                    elif arg.type == 'call':
                        # Function call with name and params
                        for call_child in arg.children:
                            if call_child.type == 'identifier':
                                metadata['name'] = self.get_node_text(call_child, source)
                                break
                        break
                    elif arg.type == 'identifier':
                        metadata['name'] = self.get_node_text(arg, source)
                        break
                break

        return metadata

    def chunk_code(self, source_code: str) -> List[TreeSitterChunk]:
        """Override to handle Elixir's call-based definition structure."""
        source_bytes = bytes(source_code, 'utf-8')
        tree = self.parser.parse(source_bytes)
        chunks: List[TreeSitterChunk] = []

        def traverse(node, parent_info=None):
            if self.should_chunk_node(node):
                start_line, end_line = self.get_line_numbers(node)
                content = self.get_node_text(node, source_bytes)
                metadata = self.extract_metadata(node, source_bytes)

                if parent_info:
                    metadata.update(parent_info)

                chunks.append(TreeSitterChunk(
                    content=content,
                    start_line=start_line,
                    end_line=end_line,
                    node_type=node.type,
                    language=self.language_name,
                    metadata=metadata,
                ))

                # For modules, traverse children to find nested defs
                def_type = metadata.get('def_type')
                if def_type in ('defmodule', 'defprotocol', 'defimpl'):
                    container_info = {
                        'parent_name': metadata.get('name'),
                        'parent_type': metadata.get('declaration_kind', 'module'),
                    }
                    for child in node.children:
                        traverse(child, container_info)
                return

            for child in node.children:
                traverse(child, parent_info)

        traverse(tree.root_node)

        if not chunks and source_code.strip():
            chunks.append(TreeSitterChunk(
                content=source_code,
                start_line=1,
                end_line=len(source_code.split('\n')),
                node_type='module',
                language=self.language_name,
                metadata={'type': 'module'},
            ))

        return chunks
