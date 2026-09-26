# Testcase Synthesis Pipeline

Synthesizes grounded, multi-skill test cases for AI agent evaluation. Each test case is a realistic user task that chains capabilities across one or more skills, with arguments and expected outputs grounded in real database or workspace state.

## How It Works

The pipeline runs in three steps:

1. **Graph** — Builds a directed capability graph from extracted skill definitions. Within-skill edges come from defined flows; cross-skill edges are identified by an LLM (GPT-5.4 via Azure).
2. **Sample** — Randomly walks the graph to produce capability chains (2–5 steps). Chains can be filtered to within-skill, cross-skill, or chains touching specific new skills.
3. **Generate** — For each chain:
   - `ClaudeDBSampler` queries `world.db` (or a workspace) via Claude Code to find real, self-consistent entities.
   - `testcase_gen.py` calls GPT-5.4 to produce a structured test case grounded in the DB snapshot.
   - `ConsistencyVerifier` spawns Claude Code to cross-check all arguments/outputs against the snapshot, fixing hallucinations or rejecting infeasible scenarios.
   - Output is saved as `test_cases.json` and converted to individual YAML files.

## Files

| File | Purpose |
|------|---------|
| `run_pipeline.py` | Orchestrates all three steps; main entry point |
| `graph.py` | Builds `CapabilityGraph` from skill definition JSONs; adds cross-skill edges via LLM |
| `sampler.py` | Random-walks the graph to produce capability chains |
| `db_sampler.py` | `ClaudeDBSampler` — queries `world.db` or workspace files via Claude Code subprocess |
| `skill_extractor.py` | Extracts structured skill definitions from `SKILL.md` files via Claude Code |
| `testcase_gen.py` | Calls GPT-5.4 to generate a test case from a chain + DB snapshot |
| `verifier.py` | `ConsistencyVerifier` — checks/fixes hallucinated values via Claude Code |
| `convert_to_yaml.py` | Converts `test_cases.json` entries to YAML format for the test harness |

## Prerequisites

```bash
export AZURE_API_KEY=...
export AZURE_API_VERSION=...
export AZURE_API_BASE=...
```

Requires: `openai`, `pyyaml`, and `claude` CLI in `PATH`.

Skill definitions must be pre-extracted into `skill_definitions/` via `skill_extractor.py` before running the pipeline.

## Usage

### 1. Extract skill definitions (run once per skill)

```bash
python testcase_synthesis/skill_extractor.py \
    --skills-dir CUGA_generalist_agent/.cuga/skills \
    --out-dir testcase_synthesis/skill_definitions \
    --skills tau2Airline state-shopping state-customer-support
```

### 2. Run the full pipeline

**T_old** — test cases for a fixed skill set:
```bash
python testcase_synthesis/run_pipeline.py \
    --skills tau2Airline state-shopping state-customer-support toolsandbox-assistant OfficeBench \
    --out testcase_synthesis/told/output/test_cases.json \
    --n 10
```

**T_new** — test cases that involve at least one new skill:
```bash
python testcase_synthesis/run_pipeline.py \
    --skills tau2Airline state-shopping state-customer-support toolsandbox-assistant OfficeBench \
    --new-skills state-travel \
    --out testcase_synthesis/tnew/output/test_cases.json \
    --n 10
```

### 3. Resume from a later step

```bash
# Graph already built — re-sample and regenerate
python testcase_synthesis/run_pipeline.py ... --from-step sample

# Chains already sampled — regenerate only
python testcase_synthesis/run_pipeline.py ... --from-step generate
```

### Key options

| Flag | Default | Description |
|------|---------|-------------|
| `--n` | 10 | Number of test cases to generate |
| `--chain-type` | `all` | `all` / `within` / `cross` |
| `--cross-skill-only` | false | Only chains spanning 2+ skills |
| `--db` | auto | Override path to `world.db` |
| `--workspace` | — | File-based skills (no DB) |
| `--sampler-model` | `claude-4.6-opus[1m]` | Claude model for DB sampling + verification |

## Output

```
<run>/output/test_cases.json      # All test cases with metadata
<run>/output/yaml_cases/<id>.yaml # One YAML per test case (for harness)
<run>/logs/                       # Claude Code subprocess logs
```

Each test case contains:
- `task_summary` — user-facing task prompt
- `expected_capabilities` — ordered list of capabilities with input arguments and expected outputs, all grounded in real DB values
- `subgoals` — verifiable assertions about agent behavior
- `_db_snapshot`, `_verification_status` — internal metadata

## Standalone Tools

```bash
# Build graph only
python testcase_synthesis/graph.py testcase_synthesis/skill_definitions/

# Sample chains only
python testcase_synthesis/sampler.py testcase_synthesis/skill_definitions/graph.json --n 10 --type cross

# Sample DB state for a specific chain
python testcase_synthesis/db_sampler.py \
    --db path/to/world.db \
    --graph testcase_synthesis/skill_definitions/graph.json \
    --defs testcase_synthesis/skill_definitions \
    --chain "state-shopping.get_cart,state-customer-support.process_return"

# Convert existing test_cases.json to YAML
python testcase_synthesis/convert_to_yaml.py \
    --input testcase_synthesis/told/output/test_cases.json \
    --out-dir testcase_synthesis/told/output/yaml_cases
```
