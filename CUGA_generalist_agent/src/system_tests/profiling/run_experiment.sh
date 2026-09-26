#!/bin/bash

# Main entry point for CUGA profiling experiments
# This is the user-facing script that should be used to run experiments

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Forward all arguments to the actual script
exec "$SCRIPT_DIR/bin/run_experiment.sh" "$@"
