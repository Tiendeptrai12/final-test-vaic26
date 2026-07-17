import sys
import os

# Define base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBS_DIR = os.path.join(BASE_DIR, "libs")

# List of library paths to add to sys.path
lib_paths = [
    os.path.join(LIBS_DIR, "Guardrails-main"),
    os.path.join(LIBS_DIR, "llama_index-main", "llama-index-core"),
    os.path.join(LIBS_DIR, "llama_index-main", "llama-index-instrumentation", "src"),
]

for path in lib_paths:
    if path not in sys.path:
        sys.path.insert(0, path)
