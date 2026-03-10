#!/usr/bin/env python3
"""Command-line tool for indexing a codebase for semantic search."""

import sys
import argparse
import logging
import os
from pathlib import Path

# Add the parent directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from common_utils import VERSION
from chunking.multi_language_chunker import MultiLanguageChunker
from embeddings.embedder import CodeEmbedder
from search.indexer import CodeIndexManager


def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def main():
    parser = argparse.ArgumentParser(
        description="Index a codebase for semantic search.",
        epilog=(
            "Examples:\n"
            "  %(prog)s /path/to/project\n"
            "  %(prog)s /path/to/project --clear --verbose\n"
            "  %(prog)s . --storage-dir /custom/location\n"
            "\n"
            "Supported languages: Python, JavaScript, TypeScript, Java, Kotlin, Go,\n"
            "Rust, C, C++, C#, Markdown, Svelte, YAML, TOML, and JSON (22 file extensions total).\n"
            "Use .agent-context-code.json or CODE_SEARCH_EXCLUDE_EXTENSIONS to skip noisy file types.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"agent-context-code {VERSION}",
    )
    parser.add_argument(
        "directory",
        help="Directory containing source files to index"
    )
    parser.add_argument(
        "--storage-dir",
        default=str(Path.home() / ".claude_code_search"),
        help="Directory to store index and embeddings (default: ~/.claude_code_search)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Batch size for embedding generation (default: 8)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing index before indexing"
    )
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    # Validate directory
    directory_path = Path(args.directory).resolve()
    if not directory_path.exists():
        logger.error(f"Directory does not exist: {directory_path} – check the path and ensure it is accessible.")
        sys.exit(1)
    
    if not directory_path.is_dir():
        logger.error(f"Path is not a directory: {directory_path} – provide a path to a directory, not a file.")
        sys.exit(1)
    
    # Setup storage (use os.path.expanduser for cross-platform ~ expansion)
    storage_dir = Path(os.path.expanduser(args.storage_dir)).resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        logger.info(f"Indexing directory: {directory_path}")
        logger.info(f"Storage directory: {storage_dir}")
        
        # Initialize components
        logger.info("Initializing components...")
        chunker = MultiLanguageChunker(str(directory_path))
        indexing_config = chunker.get_indexing_config_signature()
        
        # Initialize embedder with cache in storage directory
        models_dir = storage_dir / "models"
        models_dir.mkdir(exist_ok=True)
        embedder = CodeEmbedder(cache_dir=str(models_dir))
        
        # Initialize index manager
        index_dir = storage_dir / "index"
        index_manager = CodeIndexManager(str(index_dir))
        existing_stats = index_manager.get_stats()
        
        # Clear existing index if requested
        if args.clear:
            logger.info("Clearing existing index...")
            index_manager.clear_index()
        elif existing_stats.get('indexing_config') != indexing_config:
            logger.info(
                "Indexing configuration changed; clearing the existing index so excluded or oversized files are removed."
            )
            index_manager.clear_index()

        index_manager.set_indexing_config(indexing_config)
        
        # Chunk the codebase
        logger.info("Parsing and chunking source files...")
        chunks = chunker.chunk_directory(str(directory_path))
        
        if not chunks:
            supported = ", ".join(sorted(chunker.supported_extensions))
            logger.error(f"No supported source files found or no chunks extracted. Supported extensions: {supported}")
            sys.exit(1)
        
        logger.info(f"Generated {len(chunks)} chunks from source files")
        
        # Display some statistics
        chunk_types = {}
        file_count = {}
        
        for chunk in chunks:
            # Count chunk types
            chunk_types[chunk.chunk_type] = chunk_types.get(chunk.chunk_type, 0) + 1
            
            # Count files
            file_count[chunk.relative_path] = file_count.get(chunk.relative_path, 0) + 1
        
        logger.info(f"Chunk types: {dict(chunk_types)}")
        logger.info(f"Files processed: {len(file_count)}")
        
        # Generate embeddings
        logger.info("Generating embeddings (this may take a while)...")
        embedding_results = embedder.embed_chunks(chunks, batch_size=args.batch_size)
        
        logger.info(f"Generated {len(embedding_results)} embeddings")
        
        # Add to index
        logger.info("Building search index...")
        index_manager.add_embeddings(embedding_results)
        
        # Save index
        logger.info("Saving index to disk...")
        index_manager.save_index()
        
        # Display final statistics
        stats = index_manager.get_stats()
        model_info = embedder.get_model_info()
        
        logger.info("=" * 50)
        logger.info("INDEXING COMPLETED SUCCESSFULLY")
        logger.info("=" * 50)
        logger.info(f"Total chunks indexed: {stats['total_chunks']}")
        logger.info(f"Files processed: {stats['files_indexed']}")
        logger.info(f"Embedding dimension: {stats['embedding_dimension']}")
        logger.info(f"Index type: {stats['index_type']}")
        logger.info(f"Model: {model_info['model_name']}")
        
        if stats.get('chunk_types'):
            logger.info("\nChunk type distribution:")
            for chunk_type, count in stats['chunk_types'].items():
                logger.info(f"  {chunk_type}: {count}")
        
        if stats.get('top_tags'):
            logger.info("\nTop semantic tags:")
            for tag, count in list(stats['top_tags'].items())[:10]:
                logger.info(f"  {tag}: {count}")
        
        logger.info(f"\nStorage location: {storage_dir}")
        logger.info("\nYou can now use the MCP server for Claude Code integration:")
        logger.info(f"  python {Path(__file__).parent.parent / 'mcp_server' / 'server.py'}")
        
    except KeyboardInterrupt:
        logger.info("\nIndexing interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Indexing failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
