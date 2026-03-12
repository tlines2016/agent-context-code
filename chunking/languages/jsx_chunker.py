"""JSX-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.languages.javascript_chunker import JavaScriptChunker


class JSXChunker(JavaScriptChunker):
    """JSX-specific chunker (extends JavaScript chunker)."""

    def __init__(self):
        # JSX uses the JavaScript parser
        super().__init__()

    def _get_splittable_node_types(self) -> Set[str]:
        """JSX-specific splittable node types."""
        types = super()._get_splittable_node_types()
        # Add JSX-specific patterns
        types.add('jsx_element')
        types.add('jsx_self_closing_element')
        return types

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract JSX-specific metadata."""
        metadata = super().extract_metadata(node, source)

        # Check if it's a React component (function returning JSX)
        if node.type in ['function_declaration', 'arrow_function', 'function']:
            if self._has_jsx_children(node):
                metadata['is_component'] = True

        return metadata

    def _has_jsx_children(self, node) -> bool:
        """Check if node contains JSX elements in its subtree."""
        for child in node.children:
            if child.type in ('jsx_element', 'jsx_self_closing_element'):
                return True
            if self._has_jsx_children(child):
                return True
        return False
