"""Semantic chunking for structured configuration files."""

import json
import logging
import re
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from chunking.code_chunk import CodeChunk

logger = logging.getLogger(__name__)


STRUCTURED_DATA_EXTENSION_MAP = {
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.json': 'json',
    '.toml': 'toml',
}


class StructuredDataChunker:
    """Chunk YAML, TOML, and JSON files into semantic config sections."""

    def __init__(
        self,
        root_path: Optional[str] = None,
        max_file_lines: Optional[int] = None,
        max_file_bytes: Optional[int] = None,
    ):
        self.root_path = root_path
        self.max_file_lines = max_file_lines
        self.max_file_bytes = max_file_bytes
        self.skipped_files: List[Dict[str, Any]] = []

    def reset_skipped_files(self) -> None:
        """Clear the skipped files list (call before each indexing session)."""
        self.skipped_files = []

    def is_supported(self, file_path: str) -> bool:
        """Check whether the file extension is supported."""
        return Path(file_path).suffix.lower() in STRUCTURED_DATA_EXTENSION_MAP

    def chunk_file(self, file_path: str) -> List[CodeChunk]:
        """Chunk a structured data file into semantic config sections."""
        path = Path(file_path)
        language = STRUCTURED_DATA_EXTENSION_MAP.get(path.suffix.lower())
        if not language:
            return []

        if self.max_file_bytes is not None:
            try:
                file_size = path.stat().st_size
            except OSError as exc:
                logger.error(f"Failed to inspect structured data file {file_path}: {exc}")
                return []

            if file_size > self.max_file_bytes:
                logger.warning(
                    "Skipping structured data file %s (%s bytes exceeds limit %s bytes)",
                    file_path,
                    file_size,
                    self.max_file_bytes,
                )
                self.skipped_files.append({
                    "path": str(file_path),
                    "size_bytes": file_size,
                    "reason": f"exceeds max_file_bytes ({self.max_file_bytes})",
                })
                return []

        try:
            source_text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError as exc:
            logger.warning("Skipping non-UTF-8 structured data file %s: %s", file_path, exc)
            return []
        except OSError as exc:
            logger.error("Failed to read structured data file %s: %s", file_path, exc)
            return []

        if not source_text.strip():
            return []

        source_lines = source_text.splitlines()
        line_count = len(source_lines)

        if self.max_file_lines is not None:
            if line_count > self.max_file_lines:
                logger.warning(
                    "Skipping structured data file %s (%s lines exceeds limit %s lines)",
                    file_path,
                    line_count,
                    self.max_file_lines,
                )
                self.skipped_files.append({
                    "path": str(file_path),
                    "size_bytes": len(source_text.encode("utf-8")),
                    "reason": f"exceeds max_file_lines ({self.max_file_lines})",
                })
                return []

        try:
            documents = self._parse_source(source_text, language)
        except Exception as exc:
            logger.warning(
                "Failed to parse structured data file %s as %s: %s. Falling back to a raw document chunk.",
                file_path,
                language,
                exc,
            )
            return [
                self._build_chunk(
                    file_path=file_path,
                    name=path.stem or path.name,
                    chunk_type='document',
                    content=source_text,
                    start_line=1,
                    end_line=max(1, line_count),
                    tags=[language, 'config', 'raw'],
                )
            ]

        chunks: List[CodeChunk] = []
        multiple_documents = len(documents) > 1
        line_index = self._build_line_index(source_lines, language)

        for index, document in enumerate(documents, start=1):
            path_tokens = [f'document_{index}'] if multiple_documents else []
            chunks.extend(
                self._collect_chunks(
                    file_path=file_path,
                    value=document,
                    language=language,
                    path_tokens=path_tokens,
                    is_root=True,
                    line_index=line_index,
                    line_count=line_count,
                )
            )

        if chunks:
            return chunks

        fallback_name = 'document_1' if multiple_documents else (path.stem or path.name)
        rendered = self._render_fragment(language, fallback_name, documents[0] if documents else source_text)
        return [
            self._build_chunk(
                file_path=file_path,
                name=fallback_name,
                chunk_type='document',
                content=rendered,
                start_line=1,
                end_line=max(1, line_count),
                tags=[language, 'config', 'document'],
            )
        ]

    def _parse_source(self, source_text: str, language: str) -> List[Any]:
        """Parse source text into one or more structured documents."""
        if language == 'yaml':
            documents = [doc for doc in yaml.safe_load_all(source_text) if doc is not None]
        elif language == 'json':
            documents = [json.loads(source_text)]
        elif language == 'toml':
            documents = [tomllib.loads(source_text)]
        else:
            raise ValueError(f"Unsupported structured language: {language}")

        return documents

    def _collect_chunks(
        self,
        file_path: str,
        value: Any,
        language: str,
        path_tokens: List[str],
        is_root: bool,
        line_index: dict[str, int],
        line_count: int,
    ) -> List[CodeChunk]:
        """Collect semantic chunks for composite values and top-level entries."""
        chunks: List[CodeChunk] = []

        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                child_tokens = [*path_tokens, key_text]
                is_composite = isinstance(child, (dict, list))

                if is_root or is_composite:
                    name = self._format_path(child_tokens)
                    rendered = self._render_fragment(language, name, child)
                    start_line = self._estimate_start_line(line_index, key_text)
                    end_line = min(
                        max(1, line_count),
                        start_line + max(0, rendered.count('\n')),
                    )
                    tags = [language, 'config', 'mapping' if is_composite else 'entry']
                    if is_root:
                        tags.append('top_level')
                    chunks.append(
                        self._build_chunk(
                            file_path=file_path,
                            name=name,
                            chunk_type='config_section' if is_composite else 'config_entry',
                            content=rendered,
                            start_line=start_line,
                            end_line=end_line,
                            tags=tags,
                        )
                    )

                if is_composite:
                    chunks.extend(
                        self._collect_chunks(
                            file_path=file_path,
                            value=child,
                            language=language,
                            path_tokens=child_tokens,
                            is_root=False,
                            line_index=line_index,
                            line_count=line_count,
                        )
                    )

        elif isinstance(value, list):
            for index, child in enumerate(value):
                child_tokens = [*path_tokens, f'[{index}]']
                is_composite = isinstance(child, (dict, list))

                if is_root or is_composite:
                    name = self._format_path(child_tokens)
                    rendered = self._render_fragment(language, name, child)
                    search_token = self._find_search_token(path_tokens, index)
                    start_line = self._estimate_start_line(line_index, search_token)
                    end_line = min(
                        max(1, line_count),
                        start_line + max(0, rendered.count('\n')),
                    )
                    tags = [language, 'config', 'list']
                    if is_root:
                        tags.append('top_level')
                    chunks.append(
                        self._build_chunk(
                            file_path=file_path,
                            name=name,
                            chunk_type='config_list' if is_composite else 'config_item',
                            content=rendered,
                            start_line=start_line,
                            end_line=end_line,
                            tags=tags,
                        )
                    )

                if is_composite:
                    chunks.extend(
                        self._collect_chunks(
                            file_path=file_path,
                            value=child,
                            language=language,
                            path_tokens=child_tokens,
                            is_root=False,
                            line_index=line_index,
                            line_count=line_count,
                        )
                    )

        return chunks

    def _build_chunk(
        self,
        file_path: str,
        name: str,
        chunk_type: str,
        content: str,
        start_line: int,
        end_line: int,
        tags: List[str],
    ) -> CodeChunk:
        """Build a CodeChunk with consistent path metadata."""
        path = Path(file_path)
        folder_parts: List[str] = []
        relative_path_str = str(path)

        if self.root_path:
            try:
                rel_path = path.relative_to(self.root_path)
                folder_parts = list(rel_path.parent.parts)
                relative_path_str = str(rel_path).replace("\\", "/")
            except ValueError:
                folder_parts = [path.parent.name] if path.parent.name else []
        else:
            folder_parts = [path.parent.name] if path.parent.name else []

        return CodeChunk(
            file_path=str(path),
            relative_path=relative_path_str,
            folder_structure=folder_parts,
            chunk_type=chunk_type,
            content=content,
            start_line=max(1, start_line),
            end_line=max(start_line, end_line),
            name=name,
            parent_name=None,
            docstring=None,
            decorators=[],
            imports=[],
            complexity_score=0,
            tags=tags,
        )

    def _format_path(self, path_tokens: List[str]) -> str:
        """Format structured path tokens into a readable chunk name."""
        parts: List[str] = []
        for token in path_tokens:
            if token.startswith('[') and parts:
                parts[-1] = f"{parts[-1]}{token}"
            else:
                parts.append(token)
        return '.'.join(parts) if parts else 'document'

    def _find_search_token(self, path_tokens: List[str], index: int) -> str:
        """Choose a token to search for when estimating line numbers."""
        for token in reversed(path_tokens):
            if not token.startswith('['):
                return token
        return str(index)

    def _build_line_index(self, source_lines: List[str], language: str) -> dict[str, int]:
        """Build a best-effort first-occurrence index for config keys and sections."""
        line_index: dict[str, int] = {}

        for line_number, line in enumerate(source_lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            if language == 'yaml':
                if stripped.startswith('#'):
                    continue
                if ':' not in stripped:
                    continue
                key = stripped.split(':', 1)[0].strip()
                if key.startswith('-'):
                    key = key[1:].strip()
                key = key.strip('\'"')
                if key:
                    line_index.setdefault(key, line_number)
            elif language == 'json':
                for key in re.findall(r'"([^"\\]+)"\s*:', line):
                    line_index.setdefault(key, line_number)
            elif language == 'toml':
                if stripped.startswith('[') and stripped.endswith(']'):
                    # strip('[]') removes all leading/trailing bracket chars (covers [[…]])
                    # then .strip() removes any padding spaces inside the brackets.
                    table_name = stripped.strip('[]').strip()
                    for token in filter(None, (t.strip() for t in table_name.split('.'))):
                        line_index.setdefault(token, line_number)
                    if table_name:
                        line_index.setdefault(table_name, line_number)
                elif '=' in stripped:
                    key = stripped.split('=', 1)[0].strip().strip('\'"')
                    if key:
                        line_index.setdefault(key, line_number)

        return line_index

    def _estimate_start_line(
        self,
        line_index_or_source: str | dict[str, int],
        token: str,
        language: Optional[str] = None,
    ) -> int:
        """Best-effort estimate of the line where a key or section begins."""
        if not token:
            return 1

        if isinstance(line_index_or_source, dict):
            return line_index_or_source.get(token, 1)

        if language is None:
            return 1

        line_index = self._build_line_index(line_index_or_source.splitlines(), language)
        return line_index.get(token, 1)

    def _render_fragment(self, language: str, name: str, value: Any) -> str:
        """Render a chunk in a search-friendly, normalized text form."""
        if language == 'yaml':
            rendered_value = yaml.safe_dump(value, sort_keys=False, allow_unicode=True).strip()
        else:
            # TOML values may include datetime/date/time objects (which tomllib parses natively).
            # Provide a str fallback so they round-trip safely without crashing serialization.
            rendered_value = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False, default=str)

        return f"Path: {name}\nFormat: {language}\n{rendered_value}".strip()
