# Profiling Quick Start

## 1. Set Environment Variables

```bash
export LANGFUSE_PUBLIC_KEY="pk-..."
export LANGFUSE_SECRET_KEY="sk-..."
```

Or add to `.env` file in project root.

## 2. Run an Experiment

```bash
# Run default experiment (fast vs balanced)
./system_tests/profiling/run_experiment.sh

# Compare different providers
./system_tests/profiling/run_experiment.sh --config providers_comparison.yaml

# Compare all modes for one provider
./system_tests/profiling/run_experiment.sh --config fast_vs_accurate.yaml

# Full matrix: providers × modes
./system_tests/profiling/run_experiment.sh --config full_matrix_comparison.yaml
```

## 3. View Results

```bash
# Start HTTP server and open browser
./system_tests/profiling/serve.sh --open

# Or just start server (visit http://localhost:8080/comparison.html)
./system_tests/profiling/serve.sh
```

## Comparison Types

### Mode Comparison (Same Provider)
Compare fast vs balanced vs accurate modes using the same LLM provider.

Example output files: `fast_20250930.json`, `balanced_20250930.json`, `accurate_20250930.json`

### Provider Comparison (Same Mode)
Compare OpenAI vs Azure vs WatsonX using the same mode (e.g., balanced).

Example output files: `openai_balanced_20250930.json`, `azure_balanced_20250930.json`, `watsonx_balanced_20250930.json`

### Full Matrix Comparison
Compare all combinations of providers and modes (2 providers × 2 modes = 4 experiments).

Example output files: `openai_fast_20250930.json`, `openai_balanced_20250930.json`, `azure_fast_20250930.json`, `azure_balanced_20250930.json`

## Available Scripts

| Script | Purpose |
|--------|---------|
| `run_experiment.sh` | Run profiling experiments with YAML config |
| `serve.sh` | Start HTTP server to view results |
| `bin/run_profiling.sh` | Lower-level profiling script with CLI args |
| `bin/profile_digital_sales_tasks.py` | Core Python profiling tool |

## Configuration Files

Located in `config/`:
- `default_experiment.yaml` - Fast vs Balanced comparison
- `fast_vs_accurate.yaml` - Fast vs Accurate comparison
- `providers_comparison.yaml` - OpenAI vs Azure vs WatsonX (same mode)
- `full_matrix_comparison.yaml` - Full provider × mode matrix
- `.secrets.yaml` - Your Langfuse credentials (git-ignored)

## Example: Provider Comparison

Create or use `config/providers_comparison.yaml`:

```yaml
experiment:
  name: "providers_comparison"
  runs:
    - name: "openai_balanced"
      test_id: "settings.openai.toml:balanced:test_get_top_account_by_revenue_stream"
      iterations: 3
      output: "experiments/openai_balanced_{{timestamp}}.json"
    
    - name: "azure_balanced"
      test_id: "settings.azure.toml:balanced:test_get_top_account_by_revenue_stream"
      iterations: 3
      output: "experiments/azure_balanced_{{timestamp}}.json"
```

Then run:

```bash
./system_tests/profiling/run_experiment.sh --config providers_comparison.yaml
./system_tests/profiling/serve.sh --open
```

## Color Coding in Charts

The comparison HTML automatically color-codes experiments:

**Modes:**
- Fast = Green 🟢
- Balanced = Blue 🔵
- Accurate = Orange 🟠

**Providers:**
- OpenAI = Teal 🟦
- Azure = Azure Blue 💙
- WatsonX = IBM Blue 🔵

**Combined Labels** (e.g., `openai_balanced`) get colors based on provider first, then mode.

## Directory Structure

```
system_tests/profiling/
├── run_experiment.sh          # Main entry point
├── serve.sh                   # View results
├── bin/                       # Internal scripts
├── config/                    # YAML configurations
├── experiments/               # Results + HTML viewer
└── reports/                   # Individual reports
```

## Tips

- 💡 HTML auto-loads all JSON files in experiments/
- 💡 Naming format: `{provider}_{mode}_{timestamp}.json` or `{mode}_{timestamp}.json`
- 💡 CLI args override YAML config settings
- 💡 Use `{{timestamp}}` in output paths for unique files
- 💡 Retry mechanism handles Langfuse propagation delays
- 💡 Stop server with Ctrl+C

For full documentation, see `README.md`.