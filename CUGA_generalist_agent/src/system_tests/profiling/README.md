# CUGA Profiling

This directory contains tools for profiling CUGA digital sales tasks with different configurations and models, extracting performance metrics and LLM call information from Langfuse.

## Directory Structure

```
system_tests/profiling/
├── README.md                    # This file
├── run_experiment.sh            # Main entry point for running experiments
├── serve.sh                     # HTTP server for viewing results
├── bin/                         # Internal scripts
│   ├── profile_digital_sales_tasks.py
│   ├── run_profiling.sh
│   └── run_experiment.sh
├── config/                      # Configuration files
│   ├── default_experiment.yaml  # Default experiment configuration
│   ├── fast_vs_accurate.yaml    # Example: Fast vs Accurate comparison
│   └── .secrets.yaml            # Secrets file (git-ignored)
├── experiments/                 # Experiment results and comparison HTML
│   └── comparison.html
└── reports/                     # Individual profiling reports
```

## Quick Start

### 1. Set Up Environment Variables

Create a `.env` file in the project root or export these variables:

```bash
export LANGFUSE_PUBLIC_KEY="pk-your-public-key"
export LANGFUSE_SECRET_KEY="sk-your-secret-key"
export LANGFUSE_HOST="https://cloud.langfuse.com"  # Optional
```

### 2. Run an Experiment

The simplest way to run experiments is using the configuration files:

```bash
# Run default experiment (fast vs balanced)
./system_tests/profiling/run_experiment.sh

# Run a specific experiment configuration
./system_tests/profiling/run_experiment.sh --config fast_vs_accurate.yaml

# Run and automatically open results in browser
./system_tests/profiling/run_experiment.sh --config default_experiment.yaml --open
```

### 3. View Results

Results are automatically saved to `system_tests/profiling/experiments/` and can be viewed in the HTML dashboard:

```bash
# Start the server (serves experiments directory)
./system_tests/profiling/serve.sh

# Or start and open browser automatically
./system_tests/profiling/serve.sh --open

# Use a different port
./system_tests/profiling/serve.sh --port 3000
```

## Configuration Files

Configuration files use YAML format with Dynaconf. They define experiments with multiple runs and comparison settings.

### Example Configuration

```yaml
profiling:
  configs:
    - "settings.openai.toml"
  modes:
    - "fast"
    - "balanced"
  tasks:
    - "test_get_top_account_by_revenue_stream"
  runs: 3

experiment:
  name: "fast_vs_balanced"
  description: "Compare fast and balanced modes"
  
  runs:
    - name: "fast_mode"
      test_id: "settings.openai.toml:fast:test_get_top_account_by_revenue_stream"
      iterations: 3
      output: "experiments/fast_{{timestamp}}.json"
      env:
        MODEL_NAME: "Azure/gpt-4o"  # Set environment variable
    
    - name: "balanced_mode"
      test_id: "settings.openai.toml:balanced:test_get_top_account_by_revenue_stream"
      iterations: 3
      output: "experiments/balanced_{{timestamp}}.json"
      env:
        MODEL_NAME: null  # Unset environment variable
  
  comparison:
    generate_html: true
    html_output: "experiments/comparison.html"
    auto_open: false
```

### Configuration Options

#### Profiling Section

- `configs`: List of configuration files to test (e.g., `settings.openai.toml`)
- `modes`: List of CUGA modes (`fast`, `balanced`, `accurate`)
- `tasks`: List of test tasks to run
- `runs`: Number of iterations per configuration
- `output`: Output directory and filename settings
- `langfuse`: Langfuse connection settings (credentials from env vars)

#### Experiment Section

- `name`: Name of the experiment
- `description`: Description of what's being tested
- `runs`: List of experiment runs to execute
  - `name`: Display name for the run
  - `test_id`: Specific test to run (format: `config:mode:task`)
  - `iterations`: Number of times to run this test
  - `output`: Output file path (use `{{timestamp}}` for dynamic naming)
  - `env`: (Optional) Environment variables to set/unset for this run
    - Set a variable: `VAR_NAME: "value"`
    - Unset a variable: `VAR_NAME: null`
- `comparison`: Settings for generating comparison HTML

## Available Test IDs

Test IDs follow the format: `config:mode:task`

**Configurations:**
- `settings.openai.toml`
- `settings.azure.toml`
- `settings.watsonx.toml`

**Modes:**
- `fast`
- `balanced`
- `accurate`

**Tasks:**
- `test_get_top_account_by_revenue_stream`
- `test_list_my_accounts`
- `test_find_vp_sales_active_high_value_accounts`

To list all available test IDs:

```bash
./system_tests/profiling/bin/run_profiling.sh --list-tests
```

## Advanced Usage

### Command Line Interface

You can also use CLI arguments directly:

```bash
# Run specific configuration with CLI args
./system_tests/profiling/bin/run_profiling.sh \
  --configs settings.openai.toml \
  --modes fast,balanced \
  --runs 3

# Run a single test by ID
./system_tests/profiling/bin/run_profiling.sh \
  --test-id settings.openai.toml:fast:test_get_top_account_by_revenue_stream \
  --runs 5

# Use config file but override runs
./system_tests/profiling/bin/run_profiling.sh \
  --config-file default_experiment.yaml \
  --runs 5
```

### Direct Python Usage

```bash
# Run with config file
cd /path/to/project
uv run python system_tests/profiling/bin/profile_digital_sales_tasks.py \
  --config-file default_experiment.yaml

# Run with CLI arguments
uv run python system_tests/profiling/bin/profile_digital_sales_tasks.py \
  --configs settings.openai.toml \
  --modes fast \
  --tasks test_get_top_account_by_revenue_stream \
  --runs 3 \
  --output system_tests/profiling/reports/my_report.json
```

## Output

### Profiling Reports

Individual profiling runs generate JSON reports with:

- **Summary Statistics**: Total tests, success rate, timing
- **Configuration Stats**: Performance per config/mode
- **Langfuse Metrics**: LLM calls, tokens, costs, node timings
- **Detailed Results**: Complete test execution details

### Comparison HTML

The comparison HTML (`experiments/comparison.html`) provides:

**Interactive Visualizations:**
- 📊 Execution time comparison charts
- 💰 Cost analysis across modes
- 🎯 Token usage visualization
- 🔄 LLM calls breakdown
- 📊 Execution time variability (Min/Avg/Max with range and std dev)
- ⚡ Time breakdown (generation vs processing)
- 📈 Performance radar chart (normalized comparison)

**Detailed Tables:**
- Summary view of all experiments
- Configuration statistics table
- Per-run Langfuse metrics
- Aggregated metrics across runs

**Features:**
- Tab navigation between charts and tables
- Color-coded modes (Fast=green, Balanced=blue, Accurate=orange)
- Interactive tooltips on hover
- Automatic loading of all JSON files in the directory
- Modern, responsive design

## Creating Custom Experiments

1. Create a new YAML file in `system_tests/profiling/config/`:

```bash
cp system_tests/profiling/config/default_experiment.yaml system_tests/profiling/config/my_experiment.yaml
```

2. Edit the configuration to match your experiment needs

3. Run your experiment:

```bash
./system_tests/profiling/run_experiment.sh --config my_experiment.yaml
```

## Tips

- Use `{{timestamp}}` in output paths for unique filenames
- CLI arguments override config file settings
- The HTML comparison automatically picks up new JSON files
- Set credentials in `.env` or `config/.secrets.yaml`
- Use `--open` flag to automatically open results in browser
- Use `env` in experiment runs to set/unset environment variables per run
- Set `env.VAR: null` to explicitly unset an environment variable

## Troubleshooting

### Port Conflicts

The scripts automatically clean up processes on ports 8000, 8001, 7860.

### Missing Credentials

Ensure `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set:

```bash
# Check if set
echo $LANGFUSE_PUBLIC_KEY
echo $LANGFUSE_SECRET_KEY

# Set temporarily
export LANGFUSE_PUBLIC_KEY="pk-..."
export LANGFUSE_SECRET_KEY="sk-..."

# Or add to .env file
```

### Configuration Not Found

If a config file isn't found, check:
- The file exists in `system_tests/profiling/config/`
- The filename is correct (case-sensitive)
- You're running from the correct directory

## Examples

### Compare Fast vs Balanced (3 runs each)

```bash
./system_tests/profiling/run_experiment.sh --config default_experiment.yaml
```

### Compare Providers (OpenAI vs Azure vs WatsonX)

```bash
./system_tests/profiling/run_experiment.sh --config providers_comparison.yaml
```

This compares different LLM providers using the same mode (balanced).

### Compare All Modes with OpenAI

Create `system_tests/profiling/config/all_modes.yaml`:

```yaml
experiment:
  name: "all_modes_comparison"
  runs:
    - name: "fast"
      test_id: "settings.openai.toml:fast:test_get_top_account_by_revenue_stream"
      iterations: 5
      output: "experiments/fast_{{timestamp}}.json"
    - name: "balanced"
      test_id: "settings.openai.toml:balanced:test_get_top_account_by_revenue_stream"
      iterations: 5
      output: "experiments/balanced_{{timestamp}}.json"
    - name: "accurate"
      test_id: "settings.openai.toml:accurate:test_get_top_account_by_revenue_stream"
      iterations: 5
      output: "experiments/accurate_{{timestamp}}.json"
```

Then run:

```bash
./system_tests/profiling/run_experiment.sh --config all_modes.yaml --open
```

### Full Matrix Comparison (Providers × Modes)

```bash
./system_tests/profiling/run_experiment.sh --config full_matrix_comparison.yaml
```

This creates a comprehensive comparison across multiple providers and modes.
