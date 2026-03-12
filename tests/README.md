# Test Suite Documentation

This directory contains comprehensive tests for the AGENT Context Local system.

## Test Structure

```
tests/
├── run_tests.py              # Test runner script
├── conftest.py               # Global test configuration  
├── fixtures/                 # Test fixtures and sample data
│   ├── conftest.py          # Fixture definitions
│   └── sample_code.py       # Sample code for testing
├── unit/                     # Unit tests
│   ├── test_chunking.py     # AST chunking tests
│   ├── test_embeddings.py   # Embedding generation tests
│   ├── test_indexing.py     # Search and indexing tests
│   └── test_mcp_server.py   # MCP server tests
└── integration/              # Integration tests
    └── test_full_flow.py    # End-to-end workflow tests
```

## Running Tests

### Using the Test Runner

The test runner provides convenient options for running different test suites:

```bash
# Run all tests
./tests/run_tests.py

# Run only unit tests
./tests/run_tests.py --unit

# Run only integration tests
./tests/run_tests.py --integration

# Run specific test categories
./tests/run_tests.py --chunking    # AST chunking tests
./tests/run_tests.py --embeddings  # Embedding tests
./tests/run_tests.py --search      # Search functionality tests
./tests/run_tests.py --mcp          # MCP server tests

# Run with coverage
./tests/run_tests.py --coverage

# Run specific test files
./tests/run_tests.py unit/test_chunking.py
./tests/run_tests.py -k "test_chunking_function"

# Verbose output
./tests/run_tests.py --verbose

# Stop on first failure
./tests/run_tests.py --stop-on-first-failure
```

### Using Pytest Directly

You can also run pytest directly from the project root:

```bash
# All tests
pytest

# Specific markers
pytest -m "unit"
pytest -m "integration" 
pytest -m "chunking and not slow"

# Specific files
pytest tests/unit/test_chunking.py

# With coverage
pytest --cov=claude_embedding_search --cov-report=html
```

## Test Categories

Tests are organized by markers for easy filtering:

- **unit**: Fast unit tests for individual components
- **integration**: Slower tests that test component interactions
- **chunking**: Tests for AST-based code chunking
- **embeddings**: Tests for embedding generation  
- **search**: Tests for indexing and search functionality
- **mcp**: Tests for MCP server integration
- **slow**: Long-running tests (excluded by default)

## Test Fixtures

### Sample Codebase
The test suite includes a comprehensive sample codebase with:
- Authentication module (auth patterns, error handling)
- Database module (queries, connection management)
- API module (endpoints, request handling)
- Utilities module (helper functions)

### Temporary Directories
Tests use temporary directories for:
- Mock project structures
- Index storage during tests
- Model cache simulation

### Mock Components
Many tests use mocked versions of expensive operations:
- EmbeddingGemma model loading
- FAISS index operations
- Database connections

## Key Test Scenarios

### Unit Tests

**AST Chunking (`test_chunking.py`)**
- Function and class extraction
- Semantic tag detection
- Decorator and docstring parsing
- Complexity calculation
- Folder structure metadata
- Error handling for malformed code

**Embedding Generation (`test_embeddings.py`)**
- Model initialization and caching
- Prompt creation for different chunk types
- Batch embedding generation
- Query embedding creation
- Metadata preservation

**Indexing and Search (`test_indexing.py`)**
- FAISS index creation and management
- Metadata storage in SQLite
- Search filtering and ranking
- Similar code discovery
- Index persistence

**MCP Server (`test_mcp_server.py`)**
- Tool function implementations
- Error handling and JSON serialization
- Component initialization and caching
- Resource and prompt endpoints

### Integration Tests

**Full Workflow (`test_full_flow.py`)**
- Complete chunking → embedding → indexing → search flow
- Directory-wide indexing
- Search with various filters
- Performance characteristics
- Memory usage validation
- Error handling across components

## Running Tests in Development

### Quick Validation
```bash
# Fast unit tests only
./tests/run_tests.py --unit --quiet

# Test specific functionality
./tests/run_tests.py --chunking --verbose
```

### Pre-commit Testing
```bash
# Full test suite with coverage
./tests/run_tests.py --coverage

# Include slow tests
./tests/run_tests.py --slow
```

### Debugging Failed Tests
```bash
# Run failed tests first
./tests/run_tests.py --failed-first --verbose

# Stop on first failure for debugging
./tests/run_tests.py --stop-on-first-failure -x
```

## Test Configuration

### Pytest Settings (`pytest.ini`)
- Test discovery patterns
- Custom markers
- Warning filters
- Output formatting

### Global Fixtures (`conftest.py`)
- Automatic test marking
- Global state reset
- Path configuration

### Performance Settings
- Limited chunk processing in tests
- Small batch sizes for speed
- Mock embeddings for fast execution
- Temporary storage cleanup

## Coverage

Run with coverage to ensure comprehensive testing:

```bash
./tests/run_tests.py --coverage
```

Coverage reports are generated in:
- Terminal: Summary with missing lines
- HTML: `htmlcov/index.html` (detailed report)

Target coverage areas:
- Core chunking logic: >95%
- Embedding generation: >90%
- Search functionality: >90%
- MCP server tools: >85%
- Error handling paths: >80%

## Continuous Integration

For CI/CD pipelines, use:

```bash
# Fast, comprehensive test run
pytest -m "not slow" --cov=claude_embedding_search --cov-fail-under=85

# Full test suite (including slow tests)  
pytest --cov=claude_embedding_search --cov-fail-under=80
```

## Adding New Tests

When adding new functionality:

1. **Unit tests**: Test individual functions/classes in isolation
2. **Integration tests**: Test component interactions
3. **Fixtures**: Add sample data to `fixtures/` if needed
4. **Markers**: Use appropriate markers for test categorization
5. **Documentation**: Update this README with new test scenarios

### Test Naming Convention
- Test files: `test_<component>.py`
- Test classes: `Test<ComponentName>`
- Test methods: `test_<specific_behavior>`

### Example Test Structure
```python
class TestNewComponent:
    """Test cases for NewComponent."""
    
    def test_basic_functionality(self, fixture_name):
        """Test basic operation."""
        pass
    
    def test_error_handling(self):
        """Test error conditions."""
        pass
    
    def test_edge_cases(self):
        """Test boundary conditions.""" 
        pass
```