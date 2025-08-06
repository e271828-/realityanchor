#!/bin/bash

# This script automates the process of generating and evaluating reality anchor benchmarks
# against a local OpenAI-compatible server, such as LM Studio.

# --- Configuration ---
# The API endpoint for your local server (e.g., LM Studio, Ollama)
API_URL="http://localhost:1234/v1"

# Default model identifier if no file or argument is provided.
# You can override this by passing an argument to the script, e.g., ./run_eval.sh "gemma-2b-it"
# Or by creating a models.txt file.
DEFAULT_MODEL_NAME=${1:-"local-model"}

# File containing a list of model identifiers to test, one per line.
MODELS_FILE="models.txt"

# Number of questions to generate per domain
COUNT_PER_DOMAIN=10

# --- Script ---
set -e # Exit immediately if a command exits with a non-zero status.

echo "--- Reality Anchor Benchmark ---"
echo "Target API:   $API_URL"
echo "--------------------------------"

# Step 1: Generate fresh benchmark data for all domains
# This only runs once, creating a consistent set of questions for all models.
echo ""
echo ">>> Step 1: Generating benchmark data..."
python main.py generate --domains github,reddit,pypi,wikipedia --count $COUNT_PER_DOMAIN

# Step 2: Find all generated benchmark files and create a comma-separated list
echo ""
echo ">>> Step 2: Finding generated benchmark files..."
BENCHMARK_FILES=$(find benchmarks -name '*_benchmark.json' | tr '\n' ',' | sed 's/,$//')

if [ -z "$BENCHMARK_FILES" ]; then
    echo "Error: No benchmark files found in the 'benchmarks/' directory. Generation might have failed."
    exit 1
fi

echo "Found files: $BENCHMARK_FILES"

# Step 3: Run the evaluation against the local model(s)
echo ""
echo ">>> Step 3: Starting evaluation loop..."

# Set environment variables for the python script to use.
# OPENAI_API_KEY is often not needed for local servers, but we set it to a dummy value.
export OPENAI_API_BASE="$API_URL"
export OPENAI_API_KEY="not-needed"

# Check if a models.txt file exists
if [ -f "$MODELS_FILE" ]; then
    echo "Found $MODELS_FILE. Evaluating models listed within."
    # Loop through each line in the models.txt file
    while IFS= read -r model_name || [[ -n "$model_name" ]]; do
        # Skip empty lines
        if [ -z "$model_name" ]; then
            continue
        fi
        echo ""
        echo "--- Evaluating Model: $model_name ---"
        python main.py evaluate --model "$model_name" --benchmarks "$BENCHMARK_FILES"
    done < "$MODELS_FILE"
else
    echo "No $MODELS_FILE found. Evaluating single model: $DEFAULT_MODEL_NAME"
    echo ""
    echo "--- Evaluating Model: $DEFAULT_MODEL_NAME ---"
    python main.py evaluate --model "$DEFAULT_MODEL_NAME" --benchmarks "$BENCHMARK_FILES"
fi


echo ""
echo "--- All Evaluations Complete ---"
