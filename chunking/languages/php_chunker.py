"""PHP-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.base_chunker import LanguageChunker


class PhpChunker(LanguageChunker):
    """PHP-specific chunker using tree-sitter."""

    def __init__(self):
        super().__init__('php')

    def _get_splittable_node_types(self) -> Set[str]:
        """PHP-specific splittable node types."""
        return {
            'function_definition',
            'class_declaration',
            'method_declaration',
            'interface_declaration',
            'trait_declaration',
            'enum_declaration',
            'namespace_definition',
        }

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract PHP-specific metadata."""
        metadata = {'node_type': node.type}

        # Extract name
        for child in node.children:
            if child.type == 'name':
                metadata['name'] = self.get_node_text(child, source)
                break

        # Extract modifiers for methods and properties
        modifiers = []
        is_static = False
        for child in node.children:
            if child.type == 'visibility_modifier':
                modifiers.append(self.get_node_text(child, source))
            elif child.type == 'static_modifier':
                is_static = True
                modifiers.append('static')
            elif child.type == 'abstract_modifier':
                modifiers.append('abstract')
            elif child.type == 'final_modifier':
                modifiers.append('final')
            elif child.type == 'readonly_modifier':
                modifiers.append('readonly')

        if modifiers:
            metadata['modifiers'] = modifiers
        if is_static:
            metadata['is_static'] = True

        # Namespace name extraction
        if node.type == 'namespace_definition':
            for child in node.children:
                if child.type == 'namespace_name':
                    metadata['name'] = self.get_node_text(child, source)
                    break

        return metadata
