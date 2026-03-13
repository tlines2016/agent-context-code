"""Haskell-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.base_chunker import LanguageChunker


class HaskellChunker(LanguageChunker):
    """Haskell-specific chunker using tree-sitter."""

    def __init__(self):
        super().__init__('haskell')

    def _get_splittable_node_types(self) -> Set[str]:
        """Haskell-specific splittable node types."""
        return {
            'function',
            'signature',
            'data_type',
            'class',
            'instance',
            'type_synomym',   # Note: typo in tree-sitter-haskell grammar
            'newtype',
        }

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract Haskell-specific metadata."""
        metadata = {'node_type': node.type}

        if node.type == 'function':
            # Function name is in a 'variable' child
            for child in node.children:
                if child.type == 'variable':
                    metadata['name'] = self.get_node_text(child, source)
                    break

        elif node.type == 'signature':
            # Type signature: name :: type
            for child in node.children:
                if child.type == 'variable':
                    metadata['name'] = self.get_node_text(child, source)
                    break
            metadata['declaration_kind'] = 'signature'

        elif node.type == 'data_type':
            # data Name = Constructor ...
            for child in node.children:
                if child.type == 'name':
                    metadata['name'] = self.get_node_text(child, source)
                    break
            metadata['declaration_kind'] = 'type'

        elif node.type == 'class':
            # class ClassName a where ...
            for child in node.children:
                if child.type == 'name':
                    metadata['name'] = self.get_node_text(child, source)
                    break

        elif node.type == 'instance':
            # instance ClassName Type where ...
            names = []
            for child in node.children:
                if child.type == 'name':
                    names.append(self.get_node_text(child, source))
            if names:
                metadata['name'] = ' '.join(names)
            metadata['declaration_kind'] = 'instance'

        elif node.type == 'type_synomym':
            # type Name = Type
            for child in node.children:
                if child.type == 'name':
                    metadata['name'] = self.get_node_text(child, source)
                    break
            metadata['declaration_kind'] = 'type'

        elif node.type == 'newtype':
            # newtype Name = Constructor { ... }
            for child in node.children:
                if child.type == 'name':
                    metadata['name'] = self.get_node_text(child, source)
                    break
            metadata['declaration_kind'] = 'type'

        return metadata
