#!/usr/bin/env python3
"""Test runner script with various test execution options."""

import sys
import argparse
import subprocess
from pathlib import Path


def run_pytest(args_list):
    """Run pytest with the given arguments."""
    cmd = [sys.executable, "-m", "pytest"] + args_list
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=Path(__file__).parent)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Test runner for AGENT Context Local"
    )
    
    # Test selection options
    parser.add_argument(
        "--unit", 
        action="store_true",
        help="Run only unit tests"
    )
    parser.add_argument(
        "--integration",
        action="store_true", 
        help="Run only integration tests"
    )
    parser.add_argument(
        "--chunking",
        action="store_true",
        help="Run only chunking tests"
    )
    parser.add_argument(
        "--embeddings", 
        action="store_true",
        help="Run only embedding tests"
    )
    parser.add_argument(
        "--search",
        action="store_true",
        help="Run only search tests"
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Run only MCP server tests"
    )
    parser.add_argument(
        "--slow",
        action="store_true",
        help="Include slow tests"
    )
    
    # Output options
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Run with coverage reporting"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--quiet", "-q", 
        action="store_true",
        help="Quiet output"
    )
    parser.add_argument(
        "--failed-first",
        action="store_true",
        help="Run failed tests first"
    )
    parser.add_argument(
        "--stop-on-first-failure", "-x",
        action="store_true", 
        help="Stop on first failure"
    )
    
    # Test file/pattern
    parser.add_argument(
        "test_pattern",
        nargs="*",
        help="Specific test files or patterns to run"
    )
    
    args = parser.parse_args()
    
    # Build pytest arguments
    pytest_args = []
    
    # Add verbosity
    if args.verbose:
        pytest_args.extend(["-v", "-s"])
    elif args.quiet:
        pytest_args.append("-q")
    
    # Add failure handling
    if args.stop_on_first_failure:
        pytest_args.append("-x")
    if args.failed_first:
        pytest_args.append("--lf")
    
    # Add coverage
    if args.coverage:
        pytest_args.extend([
            "--cov=.",
            "--cov-report=html",
            "--cov-report=term-missing"
        ])
    
    # Add marker filters
    markers = []
    if args.unit:
        markers.append("unit")
    if args.integration:
        markers.append("integration") 
    if args.chunking:
        markers.append("chunking")
    if args.embeddings:
        markers.append("embeddings")
    if args.search:
        markers.append("search")
    if args.mcp:
        markers.append("mcp")
    
    if not args.slow:
        markers.append("not slow")
    
    if markers:
        pytest_args.extend(["-m", " and ".join(markers)])
    
    # Add specific test patterns
    if args.test_pattern:
        pytest_args.extend(args.test_pattern)
    
    # Run pytest
    exit_code = run_pytest(pytest_args)
    
    # Print summary (use ASCII-safe characters for Windows console compatibility)
    if exit_code == 0:
        print("\n[PASS] All tests passed!")
    else:
        print(f"\n[FAIL] Tests failed with exit code: {exit_code}")
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()