#!/bin/bash

# Digital Sales Task Profiler Runner
# This script runs the digital sales task profiler with different configurations

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$PROFILING_ROOT/../../.." && pwd)"

# Load environment variables from .env file if it exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    export $(cat "$PROJECT_ROOT/.env" | grep -v '^#' | xargs)
fi

# Default values
CONFIGS="settings.openai.toml,settings.azure.toml,settings.watsonx.toml"
MODES="fast,balanced,accurate"
TASKS="test_get_top_account_by_revenue_stream,test_list_my_accounts,test_find_vp_sales_active_high_value_accounts"
RUNS=1
OUTPUT="$PROFILING_ROOT/reports/profiling_report_$(date +%Y%m%d_%H%M%S).json"
CONFIG_FILE=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --config-file)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --configs)
            CONFIGS="$2"
            shift 2
            ;;
        --modes)
            MODES="$2"
            shift 2
            ;;
        --tasks)
            TASKS="$2"
            shift 2
            ;;
        --runs)
            RUNS="$2"
            shift 2
            ;;
        --output)
            OUTPUT="$2"
            shift 2
            ;;
        --test-id)
            TEST_ID="$2"
            shift 2
            ;;
        --list-tests)
            LIST_TESTS=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --config-file FILE   YAML configuration file to use"
            echo "  --configs CONFIGS    Comma-separated list of configs (default: $CONFIGS)"
            echo "  --modes MODES        Comma-separated list of modes (default: $MODES)"
            echo "  --tasks TASKS        Comma-separated list of tasks (default: $TASKS)"
            echo "  --runs RUNS          Number of runs per configuration (default: $RUNS)"
            echo "  --output OUTPUT      Output file for the report (default: $OUTPUT)"
            echo "  --test-id TEST_ID    Run only a specific test by ID (format: config:mode:task)"
            echo "  --list-tests         List all available test IDs and exit"
            echo "  --help               Show this help message"
            echo ""
            echo "Environment Variables Required:"
            echo "  LANGFUSE_PUBLIC_KEY  Your Langfuse public key"
            echo "  LANGFUSE_SECRET_KEY  Your Langfuse secret key"
            echo "  LANGFUSE_HOST        Langfuse host URL (optional, default: https://cloud.langfuse.com)"
            echo ""
            echo "Examples:"
            echo "  $0 --config-file default_experiment.yaml"
            echo "  $0 --configs settings.openai.toml,settings.azure.toml --modes fast,balanced --runs 3"
            echo "  $0 --test-id settings.openai.toml:fast:test_get_top_account_by_revenue_stream --runs 5"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Check for required environment variables
if [ -z "$LANGFUSE_PUBLIC_KEY" ] || [ -z "$LANGFUSE_SECRET_KEY" ]; then
    echo "Error: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY environment variables are required"
    echo "Please set them in your environment or .env file"
    exit 1
fi

# Kill any existing processes on the ports we'll use
echo "Cleaning up existing processes..."
lsof -ti:8000,8001,7860 | xargs kill -9 2>/dev/null || true

echo "Starting Digital Sales Task Profiler..."
echo "Profiling Root: $PROFILING_ROOT"

# Handle list-tests option
if [ "$LIST_TESTS" = true ]; then
    echo "Listing available test IDs..."
    cd "$PROJECT_ROOT"
    uv run python "$SCRIPT_DIR/profile_digital_sales_tasks.py" --list-tests
    exit 0
fi

# Build command based on whether config file is provided
cd "$PROJECT_ROOT"

if [ -n "$CONFIG_FILE" ]; then
    echo "Using configuration file: $CONFIG_FILE"
    CMD_ARGS="--config-file $CONFIG_FILE"
    
    # Allow CLI overrides
    [ -n "$TEST_ID" ] && CMD_ARGS="$CMD_ARGS --test-id $TEST_ID"
    [ "$RUNS" != "1" ] && CMD_ARGS="$CMD_ARGS --runs $RUNS"
    [ -n "$OUTPUT" ] && [ "$OUTPUT" != "$PROFILING_ROOT/reports/profiling_report_$(date +%Y%m%d_%H%M%S).json" ] && CMD_ARGS="$CMD_ARGS --output $OUTPUT"
else
    echo "Configurations: $CONFIGS"
    echo "Modes: $MODES"
    echo "Tasks: $TASKS"
    echo "Runs per config: $RUNS"
    echo "Output file: $OUTPUT"
    echo ""
    
    CMD_ARGS=""
    [ -n "$TEST_ID" ] && CMD_ARGS="--test-id $TEST_ID" || CMD_ARGS="--configs $CONFIGS --modes $MODES --tasks $TASKS"
    CMD_ARGS="$CMD_ARGS --runs $RUNS --output $OUTPUT"
fi

# Display environment variables if MODEL_NAME is set
echo "[DEBUG run_profiling.sh] MODEL_NAME in environment: ${MODEL_NAME:-NOT SET}"
if [ -n "$MODEL_NAME" ]; then
    echo "Environment: MODEL_NAME=$MODEL_NAME"
fi

# Run the profiler
echo "Running: uv run python $SCRIPT_DIR/profile_digital_sales_tasks.py $CMD_ARGS"
uv run python "$SCRIPT_DIR/profile_digital_sales_tasks.py" $CMD_ARGS

echo ""
echo "Profiling completed!"
