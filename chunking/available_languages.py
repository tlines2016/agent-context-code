"""Language initialization for tree-sitter based chunkers.

This module handles importing and registering available languages
for the tree-sitter based code chunking system.
"""

import logging
from tree_sitter import Language

logger = logging.getLogger(__name__)

def get_available_language():
    """
    Return a map {language: language_obj}
    """
    # Try to import language bindings
    res = {}

    try:
        import tree_sitter_python as tspython
        res['python'] = Language(tspython.language())
    except ImportError:
        logger.debug("tree-sitter-python not installed")

    try:
        import tree_sitter_javascript as tsjavascript
        res['javascript'] = Language(tsjavascript.language())
        # JavaScript also supports JSX
        res['jsx'] = res['javascript']
    except ImportError:
        logger.debug("tree-sitter-javascript not installed for JSX")

    try:
        import tree_sitter_typescript as tstypescript
        # TypeScript has two grammars: typescript and tsx
        res['typescript'] = Language(tstypescript.language_typescript())
        res['tsx'] = Language(tstypescript.language_tsx())
    except ImportError:
        logger.debug("tree-sitter-typescript not installed")

    try:
        import tree_sitter_svelte as tssvelte
        res['svelte'] = Language(tssvelte.language())
    except ImportError:
        logger.debug("tree-sitter-svelte not installed")

    try:
        import tree_sitter_go as tsgo
        res['go'] = Language(tsgo.language())
    except ImportError:
        logger.debug("tree-sitter-go not installed")

    try:
        import tree_sitter_rust as tsrust
        res['rust'] = Language(tsrust.language())
    except ImportError:
        logger.debug("tree-sitter-rust not installed")

    try:
        import tree_sitter_java as tsjava
        res['java'] = Language(tsjava.language())
    except ImportError:
        logger.debug("tree-sitter-java not installed")

    try:
        import tree_sitter_c as tsc
        res['c'] = Language(tsc.language())
    except ImportError:
        logger.debug("tree-sitter-c not installed")

    try:
        import tree_sitter_cpp as tscpp
        res['cpp'] = Language(tscpp.language())
    except ImportError:
        logger.debug("tree-sitter-cpp not installed")

    try:
        import tree_sitter_c_sharp as tscsharp
        res['csharp'] = Language(tscsharp.language())
    except ImportError:
        logger.debug("tree-sitter-c-sharp not installed")

    try:
        import tree_sitter_markdown as tsmarkdown
        res['markdown'] = Language(tsmarkdown.language())
    except ImportError:
        logger.debug("tree-sitter-markdown not installed")

    try:
        import tree_sitter_kotlin as tskotlin
        res['kotlin'] = Language(tskotlin.language())
    except ImportError:
        logger.debug("tree-sitter-kotlin not installed")

    # --- Session B: Tier 1 languages ---

    try:
        import tree_sitter_bash as tsbash
        res['bash'] = Language(tsbash.language())
    except ImportError:
        logger.debug("tree-sitter-bash not installed")

    try:
        import tree_sitter_html as tshtml
        res['html'] = Language(tshtml.language())
    except ImportError:
        logger.debug("tree-sitter-html not installed")

    try:
        import tree_sitter_css as tscss
        res['css'] = Language(tscss.language())
    except ImportError:
        logger.debug("tree-sitter-css not installed")

    # --- Session D: Tier 2 languages ---

    try:
        import tree_sitter_ruby as tsruby
        res['ruby'] = Language(tsruby.language())
    except ImportError:
        logger.debug("tree-sitter-ruby not installed")

    try:
        import tree_sitter_php as tsphp
        res['php'] = Language(tsphp.language_php())
    except ImportError:
        logger.debug("tree-sitter-php not installed")

    try:
        import tree_sitter_swift as tsswift
        res['swift'] = Language(tsswift.language())
    except ImportError:
        logger.debug("tree-sitter-swift not installed")

    try:
        import tree_sitter_sql as tssql
        res['sql'] = Language(tssql.language())
    except ImportError:
        logger.debug("tree-sitter-sql not installed")

    # --- Session D: Tier 3 languages ---

    try:
        import tree_sitter_hcl as tshcl
        res['hcl'] = Language(tshcl.language())
    except ImportError:
        logger.debug("tree-sitter-hcl not installed")

    try:
        import tree_sitter_scala as tsscala
        res['scala'] = Language(tsscala.language())
    except ImportError:
        logger.debug("tree-sitter-scala not installed")

    try:
        import tree_sitter_lua as tslua
        res['lua'] = Language(tslua.language())
    except ImportError:
        logger.debug("tree-sitter-lua not installed")

    try:
        import tree_sitter_elixir as tselixir
        res['elixir'] = Language(tselixir.language())
    except ImportError:
        logger.debug("tree-sitter-elixir not installed")

    try:
        import tree_sitter_haskell as tshaskell
        res['haskell'] = Language(tshaskell.language())
    except ImportError:
        logger.debug("tree-sitter-haskell not installed")

    return res
