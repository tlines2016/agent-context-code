"""Language-specific tree-sitter based chunkers."""

from functools import lru_cache

from chunking.languages.python_chunker import PythonChunker
from chunking.languages.javascript_chunker import JavaScriptChunker
from chunking.languages.jsx_chunker import JSXChunker
from chunking.languages.typescript_chunker import TypeScriptChunker
from chunking.languages.svelte_chunker import SvelteChunker
from chunking.languages.go_chunker import GoChunker
from chunking.languages.rust_chunker import RustChunker
from chunking.languages.java_chunker import JavaChunker
from chunking.languages.kotlin_chunker import KotlinChunker
from chunking.languages.markdown_chunker import MarkdownChunker
from chunking.languages.c_chunker import CChunker
from chunking.languages.cpp_chunker import CppChunker
from chunking.languages.csharp_chunker import CSharpChunker
from chunking.languages.bash_chunker import BashChunker
from chunking.languages.html_chunker import HtmlChunker
from chunking.languages.css_chunker import CssChunker
from chunking.languages.ruby_chunker import RubyChunker
from chunking.languages.php_chunker import PhpChunker
from chunking.languages.swift_chunker import SwiftChunker
from chunking.languages.sql_chunker import SqlChunker
from chunking.languages.hcl_chunker import HclChunker
from chunking.languages.scala_chunker import ScalaChunker
from chunking.languages.lua_chunker import LuaChunker
from chunking.languages.elixir_chunker import ElixirChunker
from chunking.languages.haskell_chunker import HaskellChunker

# Cached factory function for C++ chunker (shared across multiple extensions)
@lru_cache(maxsize=1)
def _get_cpp_chunker() -> CppChunker:
    return CppChunker()


# Map file extensions to chunker classes and language names
LANGUAGE_MAP = {
    # --- Original languages ---
    '.py': ('python', PythonChunker),
    '.js': ('javascript', JavaScriptChunker),
    '.jsx': ('jsx', JSXChunker),
    '.ts': ('typescript', lambda: TypeScriptChunker(use_tsx=False)),
    '.tsx': ('tsx', lambda: TypeScriptChunker(use_tsx=True)),
    '.svelte': ('svelte', SvelteChunker),
    '.go': ('go', GoChunker),
    '.rs': ('rust', RustChunker),
    '.java': ('java', JavaChunker),
    '.kt': ('kotlin', KotlinChunker),
    '.kts': ('kotlin', KotlinChunker),
    '.md': ('markdown', MarkdownChunker),
    '.c': ('c', CChunker),
    '.cpp': ('cpp', _get_cpp_chunker),
    '.cc': ('cpp', _get_cpp_chunker),
    '.cxx': ('cpp', _get_cpp_chunker),
    '.c++': ('cpp', _get_cpp_chunker),
    '.cs': ('csharp', CSharpChunker),
    # --- Tier 1: Shell, HTML, CSS ---
    '.sh': ('bash', BashChunker),
    '.bash': ('bash', BashChunker),
    '.zsh': ('bash', BashChunker),
    '.html': ('html', HtmlChunker),
    '.htm': ('html', HtmlChunker),
    '.css': ('css', CssChunker),
    # --- Tier 2: Ruby, PHP, Swift, SQL ---
    '.rb': ('ruby', RubyChunker),
    '.php': ('php', PhpChunker),
    '.swift': ('swift', SwiftChunker),
    '.sql': ('sql', SqlChunker),
    # --- Tier 3: HCL, Scala, Lua, Elixir, Haskell ---
    '.tf': ('hcl', HclChunker),
    '.tfvars': ('hcl', HclChunker),
    '.hcl': ('hcl', HclChunker),
    '.scala': ('scala', ScalaChunker),
    '.sc': ('scala', ScalaChunker),
    '.lua': ('lua', LuaChunker),
    '.ex': ('elixir', ElixirChunker),
    '.exs': ('elixir', ElixirChunker),
    '.hs': ('haskell', HaskellChunker),
}
