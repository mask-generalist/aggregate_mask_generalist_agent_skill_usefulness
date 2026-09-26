#!/bin/bash

# CUGA Profiling Experiment Runner
# Runs experiments using YAML configuration files and generates comparison HTML

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$PROFILING_ROOT/../../.." && pwd)"

# Load environment variables
if [ -f "$PROJECT_ROOT/.env" ]; then
    export $(cat "$PROJECT_ROOT/.env" | grep -v '^#' | xargs)
fi

# Default config file
CONFIG_FILE="default_experiment.yaml"
OPEN_BROWSER=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --open)
            OPEN_BROWSER=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --config FILE    YAML configuration file to use (default: default_experiment.yaml)"
            echo "  --open           Open comparison HTML in browser after completion"
            echo "  --help           Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --config fast_vs_accurate.yaml"
            echo "  $0 --config default_experiment.yaml --open"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

echo "=== CUGA Profiling Experiment Runner ==="
echo "Configuration file: $CONFIG_FILE"
echo ""

# Create experiments directory if it doesn't exist
mkdir -p "$PROFILING_ROOT/experiments"

# Check if config file exists
CONFIG_PATH="$PROFILING_ROOT/config/$CONFIG_FILE"
if [ ! -f "$CONFIG_PATH" ]; then
    echo "Error: Configuration file not found: $CONFIG_PATH"
    echo "Available configurations:"
    ls -1 "$PROFILING_ROOT/config/"*.yaml 2>/dev/null || echo "  No configuration files found"
    exit 1
fi

# Parse the YAML config file to extract experiment runs using Python
cd "$PROJECT_ROOT"
EXPERIMENT_DATA=$(uv run python -c "
from dynaconf import Dynaconf
from datetime import datetime
import json

config = Dynaconf(settings_files=['$CONFIG_PATH'], environments=False)

if hasattr(config, 'experiment') and hasattr(config.experiment, 'runs'):
    runs = []
    for run in config.experiment.runs:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output = run.output.replace('{{timestamp}}', timestamp)
        # Extract env block if present (convert Dynaconf object to dict safely)
        env_block = {}
        if hasattr(run, 'env') and run.env is not None:
            try:
                env_block = dict(run.env)
            except Exception:
                # Fallback: best-effort conversion
                env_block = {k: getattr(run.env, k) for k in dir(run.env) if not k.startswith('_') and not callable(getattr(run.env, k))}

        runs.append({
            'name': run.name,
            'test_id': run.test_id,
            'iterations': run.iterations,
            'output': output,
            'env': env_block
        })
    print(json.dumps(runs))
else:
    # Fallback to simple profiling run
    print('[]')
")

if [ "$EXPERIMENT_DATA" = "[]" ]; then
    echo "No experiment runs defined in config file."
    echo "Running simple profiling with config file..."
    "$SCRIPT_DIR/run_profiling.sh" --config-file "$CONFIG_FILE"
    exit 0
fi

# Run each experiment
echo "$EXPERIMENT_DATA" | uv run python -c "
import json
import sys
import subprocess
import os

runs = json.load(sys.stdin)
profiling_root = '$PROFILING_ROOT'
project_root = '$PROJECT_ROOT'
script_dir = '$SCRIPT_DIR'

for run in runs:
    print(f\"\\n{'='*60}\")
    print(f\"Running {run['name']}: {run['test_id']}\")
    print(f\"Iterations: {run['iterations']}\")
    
    # Handle environment variables
    env_vars = run.get('env', {})
    print(f\"[DEBUG run_experiment.sh] env_vars from YAML: {env_vars}\")
    if env_vars:
        print(f\"Environment variables:\")
        for key, value in env_vars.items():
            if value is None:
                print(f\"  {key}: <unset>\")
            else:
                print(f\"  {key}: {value}\")
        
        # Validate MODEL_NAME if it's being configured
        if 'MODEL_NAME' in env_vars:
            if env_vars['MODEL_NAME'] is not None:
                print(f\"  ✓ MODEL_NAME will be exported: {env_vars['MODEL_NAME']}\")
            else:
                print(f\"  ✓ MODEL_NAME will be unset (using default from config)\")
    
    print(f\"{'='*60}\\n\")
    
    # Ensure output directory exists
    output_path = os.path.join(profiling_root, run['output'])
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)
    
    # Prepare environment
    env = os.environ.copy()
    for key, value in env_vars.items():
        if value is None:
            # Unset the variable
            env.pop(key, None)
        else:
            # Set the variable
            env[key] = str(value)
    
    # Debug: Show MODEL_NAME in environment
    if 'MODEL_NAME' in env:
        print(f\"[DEBUG] MODEL_NAME in subprocess environment: {env['MODEL_NAME']}\")
    else:
        print(f\"[DEBUG] MODEL_NAME not in subprocess environment\")
    
    # Build the command - make sure script is executable
    script_path = os.path.join(script_dir, 'run_profiling.sh')
    
    # Run the profiling with explicit environment
    cmd = [
        script_path,
        '--test-id', run['test_id'],
        '--runs', str(run['iterations']),
        '--output', output_path
    ]
    
    print(f\"[DEBUG] Running command: {' '.join(cmd)}\")
    print(f\"[DEBUG] Working directory: {project_root}\")
    print(f\"[DEBUG] MODEL_NAME in env dict: {'MODEL_NAME' in env}\")
    
    result = subprocess.run(cmd, cwd=project_root, env=env, shell=False)
    
    if result.returncode != 0:
        print(f\"Error: {run['name']} failed with exit code {result.returncode}\")
        sys.exit(1)
    
    print(f\"\\n{run['name']} completed! Results saved to: {output_path}\")

print('\\n' + '='*60)
print('All experiment runs completed!')
print('='*60)
"

echo ""
echo "Experiment completed!"
echo "View results in: $PROFILING_ROOT/experiments/comparison.html"
echo ""
echo "To view results, run:"
echo "  $PROFILING_ROOT/serve.sh --open"

# Open browser if requested
if [ "$OPEN_BROWSER" = true ]; then
    echo ""
    echo "Opening browser..."
    "$PROFILING_ROOT/serve.sh" --open &
    sleep 2
fi
