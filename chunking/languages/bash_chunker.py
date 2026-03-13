"""Bash/Shell-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.base_chunker import LanguageChunker


class BashChunker(LanguageChunker):
    """Bash/Shell-specific chunker using tree-sitter."""

    def __init__(self):
        super().__init__('bash')

    def _get_splittable_node_types(self) -> Set[str]:
        """Bash-specific splittable node types."""
        return {
            'function_definition',
        }

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract Bash-specific metadata."""
        metadata = {'node_type': node.type}

        # Extract function name from 'word' child
        for child in node.children:
            if child.type == 'word':
                metadata['name'] = self.get_node_text(child, source)
                break

        return metadata
