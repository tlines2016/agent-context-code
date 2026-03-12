"""HTML-specific tree-sitter based chunker."""

from typing import Any, Dict, List, Set

from chunking.base_chunker import LanguageChunker, TreeSitterChunk


class HtmlChunker(LanguageChunker):
    """HTML-specific chunker using tree-sitter.

    Extracts script and style elements as separate chunks.
    Remaining HTML content is treated as a template chunk.
    """

    # Tags that warrant their own chunk
    _SECTION_TAGS = frozenset({
        'script', 'style', 'head', 'body', 'main', 'nav',
        'header', 'footer', 'section', 'article', 'aside', 'form', 'template',
    })

    def __init__(self):
        super().__init__('html')

    def _get_splittable_node_types(self) -> Set[str]:
        """Not used directly — chunk_code is overridden."""
        return set()

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract HTML-specific metadata."""
        metadata = {'node_type': node.type}
        tag_name = self._get_tag_name(node, source)
        if tag_name:
            metadata['name'] = f'<{tag_name}>'
            metadata['tag_name'] = tag_name
        return metadata

    def chunk_code(self, source_code: str) -> List[TreeSitterChunk]:
        """Override to chunk HTML by meaningful structural elements."""
        source_bytes = bytes(source_code, 'utf-8')
        tree = self.parser.parse(source_bytes)
        chunks: List[TreeSitterChunk] = []

        def find_sections(node):
            """Recursively find elements with meaningful tag names."""
            # tree-sitter-html uses 'script_element' and 'style_element' as
            # distinct node types rather than plain 'element'.
            if node.type in ('element', 'script_element', 'style_element'):
                tag_name = self._get_tag_name(node, source_bytes)
                if tag_name in self._SECTION_TAGS:
                    start_line, end_line = self.get_line_numbers(node)
                    content = self.get_node_text(node, source_bytes)
                    metadata = {
                        'node_type': 'element',
                        'name': f'<{tag_name}>',
                        'tag_name': tag_name,
                    }
                    if tag_name == 'script':
                        metadata['declaration_kind'] = 'script'
                    elif tag_name == 'style':
                        metadata['declaration_kind'] = 'style'
                    chunks.append(TreeSitterChunk(
                        content=content,
                        start_line=start_line,
                        end_line=end_line,
                        node_type='element',
                        language=self.language_name,
                        metadata=metadata,
                    ))
                    # Continue recursing to find nested sections (e.g.
                    # script/style inside body)

            for child in node.children:
                find_sections(child)

        find_sections(tree.root_node)

        # Fallback: if no sections found, create a single document chunk
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

    def _get_tag_name(self, node: Any, source: bytes) -> str:
        """Extract the tag name from an element node."""
        for child in node.children:
            if child.type == 'start_tag':
                for tag_child in child.children:
                    if tag_child.type == 'tag_name':
                        return self.get_node_text(tag_child, source).lower()
        return ''
