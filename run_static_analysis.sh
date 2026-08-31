#!/bin/bash
# Static analysis script for frame sync code
# Usage: ./run_static_analysis.sh

set -e

echo "=== Running Static Analysis ==="

# Check if clang-tidy is available
if ! command -v clang-tidy &> /dev/null; then
    echo "Error: clang-tidy not found. Install with:"
    echo "  sudo yum install clang-tools-extra"
    exit 1
fi

# Check if compile_commands.json exists
if [ ! -f "engine/tests/build_tests/compile_commands.json" ]; then
    echo "Error: compile_commands.json not found"
    echo "Please build with: cmake -S engine/tests -B engine/tests/build_tests -DCMAKE_EXPORT_COMPILE_COMMANDS=1"
    exit 1
fi

# Run clang-tidy on frame sync headers
echo ""
echo "Analyzing frame sync headers..."
clang-tidy \
    --config=.clang-tidy \
    --p=engine/tests/build_tests \
    engine/src/frame_sync/*.hpp \
    2>&1 | grep -E "(warning|error)" || true

echo ""
echo "=== Static Analysis Complete ==="
