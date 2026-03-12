"""Ruby-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.base_chunker import LanguageChunker


class RubyChunker(LanguageChunker):
    """Ruby-specific chunker using tree-sitter."""

    def __init__(self):
        super().__init__('ruby')

    def _get_splittable_node_types(self) -> Set[str]:
        """Ruby-specific splittable node types."""
        return {
            'method',
            'singleton_method',
            'class',
            'module',
        }

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract Ruby-specific metadata."""
        metadata = {'node_type': node.type}

        if node.type in ('class', 'module'):
            # Name is a 'constant' child
            for child in node.children:
                if child.type == 'constant':
                    metadata['name'] = self.get_node_text(child, source)
                    break
            if node.type == 'module':
                metadata['declaration_kind'] = 'module'

        elif node.type == 'method':
            # Name is an 'identifier' child
            for child in node.children:
                if child.type == 'identifier':
                    metadata['name'] = self.get_node_text(child, source)
                    break

        elif node.type == 'singleton_method':
            # def self.method_name — extract the identifier after '.'
            for child in node.children:
                if child.type == 'identifier':
                    metadata['name'] = self.get_node_text(child, source)
                    # Don't break — we want the last identifier (after self.)
            metadata['is_static'] = True

        return metadata
