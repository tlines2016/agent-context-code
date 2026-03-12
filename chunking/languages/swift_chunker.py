"""Swift-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.base_chunker import LanguageChunker


class SwiftChunker(LanguageChunker):
    """Swift-specific chunker using tree-sitter.

    Note: tree-sitter-swift uses 'class_declaration' for class, struct, enum,
    and extension declarations. The actual kind is determined by the first
    keyword child (class/struct/enum/extension).
    """

    def __init__(self):
        super().__init__('swift')

    def _get_splittable_node_types(self) -> Set[str]:
        """Swift-specific splittable node types."""
        return {
            'function_declaration',
            'class_declaration',
            'protocol_declaration',
            'init_declaration',
            'property_declaration',
        }

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract Swift-specific metadata."""
        metadata = {'node_type': node.type}

        if node.type == 'class_declaration':
            # Determine actual kind: class, struct, enum, or extension
            kind = 'class'
            for child in node.children:
                if child.type in ('class', 'struct', 'enum', 'extension'):
                    kind = child.type
                    break

            # Extract name from type_identifier
            for child in node.children:
                if child.type == 'type_identifier':
                    metadata['name'] = self.get_node_text(child, source)
                    break
                elif child.type == 'user_type':
                    # Extension uses user_type for the extended type
                    metadata['name'] = self.get_node_text(child, source)
                    break

            metadata['declaration_kind'] = kind
            if kind == 'enum':
                metadata['declaration_kind'] = 'enum'

        elif node.type == 'function_declaration':
            # Extract function name from simple_identifier
            for child in node.children:
                if child.type == 'simple_identifier':
                    metadata['name'] = self.get_node_text(child, source)
                    break

            # Check for modifiers (static, async, etc.)
            for child in node.children:
                if child.type == 'modifiers':
                    mod_text = self.get_node_text(child, source)
                    if 'static' in mod_text:
                        metadata['is_static'] = True
                    if 'async' in mod_text:
                        metadata['is_async'] = True

        elif node.type == 'protocol_declaration':
            for child in node.children:
                if child.type == 'type_identifier':
                    metadata['name'] = self.get_node_text(child, source)
                    break
            metadata['declaration_kind'] = 'protocol'

        elif node.type == 'init_declaration':
            metadata['name'] = 'init'

        elif node.type == 'property_declaration':
            # Extract property name from pattern child
            for child in node.children:
                if child.type == 'pattern':
                    metadata['name'] = self.get_node_text(child, source)
                    break

        return metadata
