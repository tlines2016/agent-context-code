"""Lua-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.base_chunker import LanguageChunker


class LuaChunker(LanguageChunker):
    """Lua-specific chunker using tree-sitter."""

    def __init__(self):
        super().__init__('lua')

    def _get_splittable_node_types(self) -> Set[str]:
        """Lua-specific splittable node types."""
        return {
            'function_declaration',
        }

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract Lua-specific metadata."""
        metadata = {'node_type': node.type}

        if node.type == 'function_declaration':
            # Check for 'local' keyword
            for child in node.children:
                if child.type == 'local':
                    metadata['is_local'] = True
                    break

            # Name can be an identifier or method_index_expression (Obj:method)
            for child in node.children:
                if child.type == 'identifier':
                    metadata['name'] = self.get_node_text(child, source)
                    break
                elif child.type == 'method_index_expression':
                    metadata['name'] = self.get_node_text(child, source)
                    break
                elif child.type == 'dot_index_expression':
                    metadata['name'] = self.get_node_text(child, source)
                    break

        return metadata
