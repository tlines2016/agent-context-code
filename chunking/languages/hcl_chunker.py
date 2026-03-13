"""HCL/Terraform-specific tree-sitter based chunker."""

from typing import Any, Dict, Set

from chunking.base_chunker import LanguageChunker


class HclChunker(LanguageChunker):
    """HCL/Terraform-specific chunker using tree-sitter.

    Handles .tf, .tfvars, and .hcl files. Chunks by top-level blocks
    (resource, data, variable, output, module, provider, locals, terraform).
    """

    def __init__(self):
        super().__init__('hcl')

    def _get_splittable_node_types(self) -> Set[str]:
        """HCL-specific splittable node types."""
        return {
            'block',
        }

    def extract_metadata(self, node: Any, source: bytes) -> Dict[str, Any]:
        """Extract HCL-specific metadata."""
        metadata = {'node_type': node.type}

        if node.type == 'block':
            # First identifier is block type (resource, variable, output, etc.)
            # Subsequent string_lit children are the block labels
            block_type = None
            labels = []
            for child in node.children:
                if child.type == 'identifier' and block_type is None:
                    block_type = self.get_node_text(child, source)
                elif child.type == 'string_lit':
                    # Extract content between quotes
                    text = self.get_node_text(child, source)
                    # Remove surrounding quotes
                    for c in child.children:
                        if c.type == 'template_literal':
                            labels.append(self.get_node_text(c, source))
                            break

            if block_type:
                metadata['block_type'] = block_type
                if labels:
                    metadata['name'] = f'{block_type} {" ".join(labels)}'
                else:
                    metadata['name'] = block_type

        return metadata
