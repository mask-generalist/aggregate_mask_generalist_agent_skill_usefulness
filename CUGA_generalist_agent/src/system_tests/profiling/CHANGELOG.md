# Profiling System Changelog

## 2025-09-29 - Major Reorganization

### Added
- ✅ Organized all profiling-related files into `system_tests/profiling/` directory
- ✅ YAML configuration support using Dynaconf
- ✅ Retry mechanism with exponential backoff for Langfuse data fetching
- ✅ Main entry point script: `run_experiment.sh`
- ✅ HTTP server script: `serve.sh` for viewing results
- ✅ Interactive charts and visualizations in comparison HTML
- ✅ Environment variable configuration per experiment run
- ✅ Provider comparison support (OpenAI vs Azure vs WatsonX)
- ✅ Comprehensive documentation with examples

### Interactive Visualizations
- 📊 Bar charts for execution time, cost, tokens, and LLM calls
- 📊 Variability chart showing Min/Avg/Max execution times with:
  - Range calculation (Max - Min)
  - Standard deviation for statistical analysis
  - Coefficient of variation (CV%) for relative consistency
- ⚡ Stacked bar chart for time breakdown
- 📈 Radar chart for normalized performance comparison
- 🎨 Color-coded modes with modern UI design
- 📋 Tab navigation between charts and detailed tables

### Structure
```
system_tests/profiling/
├── run_experiment.sh          # Main entry point for users
├── bin/                        # Internal scripts
│   ├── profile_digital_sales_tasks.py
│   ├── run_profiling.sh
│   └── run_experiment.sh
├── config/                     # YAML configurations
│   ├── default_experiment.yaml
│   ├── fast_vs_accurate.yaml
│   └── .secrets.yaml
├── experiments/                # Experiment results
│   └── comparison.html
└── reports/                    # Individual profiling reports
```

### Configuration Features
- **YAML-based configuration** with Dynaconf integration
- **CLI arguments override** config file settings
- **Environment variable support** for credentials
- **Flexible experiment definitions** with multiple runs
- **Configurable retry settings** for Langfuse data fetching

### Retry Mechanism
- **Exponential backoff**: Starting at 2s, multiplying by 1.5x each attempt
- **Smart detection**: Checks for 404 errors and incomplete observations
- **Configurable**: Set `max_attempts` and `initial_delay` in YAML
- **Default**: 10 attempts over ~60 seconds total wait time

### Migration from Old Structure
Old files moved/removed:
- `profile_digital_sales_tasks.py` → `system_tests/profiling/bin/`
- `run_profiling.sh` → `system_tests/profiling/bin/`
- `run_experiment.sh` → `system_tests/profiling/bin/` (rewritten)
- `update_html.py` → removed (HTML loads JSON dynamically)
- `PROFILING_README.md` → `system_tests/profiling/README.md`
- `experiments/` → `system_tests/profiling/experiments/`
- `profiling_report_*.json` → `system_tests/profiling/reports/`

### Usage
```bash
# Run experiment with config file
./system_tests/profiling/run_experiment.sh

# With specific config
./system_tests/profiling/run_experiment.sh --config fast_vs_accurate.yaml

# View results in browser
./system_tests/profiling/serve.sh --open

# Serve on different port
./system_tests/profiling/serve.sh --port 3000
```

### Breaking Changes
- Old scripts at project root no longer work
- Use `./system_tests/profiling/run_experiment.sh` instead
- Configuration now uses YAML instead of CLI-only

### Benefits
- 📁 Better organization - all profiling files in one place
- ⚙️ Easier configuration - YAML files instead of long CLI commands
- 🔄 More reliable - retry mechanism for Langfuse data
- 📊 Automatic HTML generation - no need to run update script
- 🎯 Clear entry point - single script for users
