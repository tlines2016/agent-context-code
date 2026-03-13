"""SQL-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.base_chunker import LanguageChunker


class SqlChunker(LanguageChunker):
    """SQL-specific chunker using tree-sitter."""

    def __init__(self):
        super().__init__('sql')

    def _get_splittable_node_types(self) -> Set[str]:
        """SQL-specific splittable node types."""
        return {
            'create_table',
            'create_view',
            'create_index',
            'create_function',
            'create_type',
            'create_trigger',
        }

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract SQL-specific metadata."""
        metadata = {'node_type': node.type}

        # Map node types to readable declaration kinds
        kind_map = {
            'create_table': 'table',
            'create_view': 'view',
            'create_index': 'index',
            'create_function': 'function',
            'create_type': 'type',
            'create_trigger': 'trigger',
        }
        metadata['declaration_kind'] = kind_map.get(node.type, node.type)

        # Extract name from object_reference or identifier child
        for child in node.children:
            if child.type == 'object_reference':
                for ref_child in child.children:
                    if ref_child.type == 'identifier':
                        metadata['name'] = self.get_node_text(ref_child, source)
                        break
                break
            elif child.type == 'identifier':
                metadata['name'] = self.get_node_text(child, source)
                break

        return metadata
