"""CSS-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.base_chunker import LanguageChunker


class CssChunker(LanguageChunker):
    """CSS-specific chunker using tree-sitter."""

    def __init__(self):
        super().__init__('css')

    def _get_splittable_node_types(self) -> Set[str]:
        """CSS-specific splittable node types."""
        return {
            'rule_set',
            'media_statement',
            'keyframes_statement',
            'import_statement',
            'supports_statement',
            'charset_statement',
        }

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract CSS-specific metadata."""
        metadata = {'node_type': node.type}

        if node.type == 'rule_set':
            # Extract selector text
            for child in node.children:
                if child.type == 'selectors':
                    metadata['name'] = self.get_node_text(child, source).strip()
                    break

        elif node.type == 'media_statement':
            metadata['name'] = '@media'
            # Extract media query condition
            for child in node.children:
                if child.type == 'feature_query':
                    metadata['name'] = f'@media {self.get_node_text(child, source).strip()}'
                    break

        elif node.type == 'keyframes_statement':
            # Extract animation name
            for child in node.children:
                if child.type == 'keyframes_name':
                    metadata['name'] = f'@keyframes {self.get_node_text(child, source).strip()}'
                    break

        elif node.type == 'import_statement':
            metadata['name'] = '@import'

        elif node.type == 'supports_statement':
            metadata['name'] = '@supports'

        elif node.type == 'charset_statement':
            metadata['name'] = '@charset'

        return metadata
