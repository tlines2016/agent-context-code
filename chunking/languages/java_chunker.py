"""Java-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.base_chunker import LanguageChunker


class JavaChunker(LanguageChunker):
    """Java-specific chunker using tree-sitter."""

    def __init__(self):
        super().__init__('java')

    def _get_splittable_node_types(self) -> Set[str]:
        """Java-specific splittable node types."""
        return {
            'method_declaration',
            'constructor_declaration',
            'class_declaration',
            'interface_declaration',
            'enum_declaration',
            'annotation_type_declaration',
            'record_declaration',
        }

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract Java-specific metadata."""
        metadata = {'node_type': node.type}

        # Extract name
        for child in node.children:
            if child.type == 'identifier':
                metadata['name'] = self.get_node_text(child, source)
                break

        # Extract access modifiers
        modifiers = []
        for child in node.children:
            if child.type == 'modifiers':
                for modifier in child.children:
                    if modifier.type in ['public', 'private', 'protected', 'static', 'final', 'abstract', 'synchronized', 'sealed', 'non-sealed']:
                        modifiers.append(self.get_node_text(modifier, source))

        if modifiers:
            metadata['modifiers'] = modifiers

        # Mark records with declaration_kind for chunk_type mapping
        if node.type == 'record_declaration':
            metadata['declaration_kind'] = 'record'

        # Check for generic parameters
        for child in node.children:
            if child.type == 'type_parameters':
                metadata['has_generics'] = True
                break

        return metadata
