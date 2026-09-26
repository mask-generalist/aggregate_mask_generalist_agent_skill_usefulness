# Running the Pi Agent Evaluation

Step-by-step instructions for building and running the pi agent with Azure Anthropic, then executing the `experiment_clean` evaluation pipeline.

---

## Prerequisites

- **Docker** installed and running
- **Node.js 24+** (the Docker build uses `node:24-bookworm-slim`)
- **Python 3.12** via pyenv (or system)
- Access to the `agent_inspect` repo at `../agent_quality_inspect` (provides `agent_inspect`)
- An Azure AI key for the `azure-anthropic` provider

---

## Part 1: One-Time Setup

This scrapes model catalogs and writes JSON shards under `packages/ai/src/providers/data/`.

### 1. Build the Docker image

**Set your Azure endpoint first.** Edit `baseUrl` in [`docker-pi/models.json`](docker-pi/models.json)
to your Azure endpoint before building — it's baked into the image, and pi does **not** read
`$AZURE_API_BASE` for it (a literal `$AZURE_API_BASE` fails with `Invalid URL`). Leave `apiKey` as
`$AZURE_API_KEY`. Example: 
>
> ```json
> "baseUrl": "https://<your-resource>.services.ai.azure.com/anthropic",
> ```

Run from the `pi_agent/` root (not from `docker-pi/`):

```bash
export AZURE_API_KEY=<your-azure-key>
docker build -t pi-sandbox -f docker-pi/Dockerfile .
```

### 2. Set up the Python environment

```bash
# Create a venv with Python 3.12
pyenv local 3.12
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

`requirements.txt` installs `litellm`, `backoff`, and the editable `agent-eval` package:

```
litellm
backoff
-e /path/to/agent-eval
```

> Update the `-e` path if your `agent-eval` repo is in a different location.

---

## Part 2: Running an Evaluation

Two terminals are required: one for the pi server and one for the evaluation runner.

### Terminal 1 — Start the pi server

```bash
cd pi_agent/
source .venv/bin/activate
# You dont need /anthropic in the base URL here, just the base of your Azure endpoint
# Example: https://<your-resource>.services.ai.azure.com/
export AZURE_API_BASE=<your-azure-base-url> 
export AZURE_API_KEY=<your-azure-key>
python docker-pi/pi_server.py
```

The server starts on `http://localhost:8000`. Leave this running for the duration of the evaluation.

### Terminal 2 — Run the evaluation pipeline

```bash
cd pi_agent/
source .venv/bin/activate

export AZURE_API_KEY=<your-azure-key>
export AZURE_API_VERSION=<your-azure-api-version>
export AZURE_API_BASE=<your-azure-base-url>

python -m experiment_clean.e2e ../testcases/pi_settings1_testcases/ \
    --n-trials 1 \
    --max-workers 7 \
    --config experiment_clean/runner_config.yaml
```

Replace `pi_settings1_testcases/` with `pi_settings2_testcases/` or
`pi_settings3_testcases/` for other test case sets. The test cases live at
the repository root under `testcases/` (one level above `pi_agent/`).

Results are written to `experiment_clean/experiment_results/jobs/<timestamp>/`.

---

## Notes

- **`AZURE_API_KEY`** is required by `pi_server.py` at startup. It is read from the container environment and injected into requests to the Azure Anthropic endpoint (see [docker-pi/models.json](docker-pi/models.json)).
