"""Scala-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.base_chunker import LanguageChunker


class ScalaChunker(LanguageChunker):
    """Scala-specific chunker using tree-sitter."""

    def __init__(self):
        super().__init__('scala')

    def _get_splittable_node_types(self) -> Set[str]:
        """Scala-specific splittable node types."""
        return {
            'class_definition',
            'object_definition',
            'trait_definition',
            'function_definition',
            'function_declaration',
            'val_definition',
            'var_definition',
            'type_definition',
        }

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract Scala-specific metadata."""
        metadata = {'node_type': node.type}

        # Extract name — most nodes use 'identifier', but type_definition
        # uses 'type_identifier' in the tree-sitter-scala grammar.
        for child in node.children:
            if child.type in ('identifier', 'type_identifier'):
                metadata['name'] = self.get_node_text(child, source)
                break

        if node.type == 'class_definition':
            # Check for case class
            is_case = False
            is_sealed = False
            for child in node.children:
                if child.type == 'case':
                    is_case = True
                elif child.type == 'modifiers':
                    mod_text = self.get_node_text(child, source)
                    if 'sealed' in mod_text:
                        is_sealed = True
                    if 'case' in mod_text:
                        is_case = True
                    if 'abstract' in mod_text:
                        metadata['is_abstract'] = True

            if is_case:
                metadata['is_case_class'] = True
            if is_sealed:
                metadata['is_sealed'] = True

        elif node.type == 'object_definition':
            metadata['declaration_kind'] = 'object'

        elif node.type == 'trait_definition':
            metadata['declaration_kind'] = 'trait'
            for child in node.children:
                if child.type == 'modifiers':
                    mod_text = self.get_node_text(child, source)
                    if 'sealed' in mod_text:
                        metadata['is_sealed'] = True

        elif node.type in ('val_definition', 'var_definition'):
            metadata['declaration_kind'] = 'property'

        elif node.type == 'type_definition':
            metadata['declaration_kind'] = 'type'

        return metadata
