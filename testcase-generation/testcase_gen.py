"""Test case generator for multi-skill mock system.

Input:
  - Sampled capability chain (with descriptions from graph)
  - DB snapshot (from db_sampler — real entities from world.db)
  - Skill definitions (from skill_extractor — descriptions, input/output schemas)

Output:
  {
    "id": "tc_...",
    "task_summary": "You are ...",
    "expected_capabilities": [
      {
        "name": "get_order",
        "skill": "state-customer-support",
        "description": "...",
        "input_schema": {"order_id": {"type": "string", "description": "...", "required": true}},
        "output_schema": {"order_id": {"type": "string", "description": "..."}, ...},
        "arguments": {"order_id": "ORD-028E0E"},
        "expected_output": {...}    # grounded in real DB values
      },
      ...
    ],
    "subgoals": [
      {"description": "Agent retrieved order ORD-028E0E and confirmed it belongs to shop_003"},
      ...
    ]
  }

Follows agent-synth LLMGenerator pattern.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from openai import AzureOpenAI

DEPLOYMENT = "gpt-5.4"


def make_client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=os.environ["AZURE_API_KEY"],
        api_version=os.environ["AZURE_API_VERSION"],
        azure_endpoint=os.environ["AZURE_API_BASE"],
    )


def _chat(client: AzureOpenAI, prompt: str, system: str = "", max_tokens: int = 4000) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=messages,
        max_completion_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def _parse_json(raw: str) -> dict | list | None:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    for start in ["{", "["]:
        idx = raw.find(start)
        if idx != -1:
            raw = raw[idx:]
            break
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ── Schema enrichment ─────────────────────────────────────────────────────────

ENRICH_SYSTEM = """You are enriching tool/capability schemas for test case generation.
Your output must be valid JSON. Use ONLY information from the skill definition provided."""

ENRICH_PROMPT = """\
The following capability is missing descriptions on some input/output schema fields.
Add concise descriptions (1 sentence max) to any field that lacks one.
Do NOT change field names, types, or required flags. Do NOT add new fields.

Capability: {name}
Skill: {skill}
Current schema:
{schema_json}

Return ONLY the corrected JSON object with the same structure but descriptions added:
{{"input_schema": {{...}}, "output_schema": {{...}}}}
"""


def _ensure_descriptions(cap: dict, client: AzureOpenAI) -> dict:
    """Ensure every input/output schema field has a description. Calls LLM if missing."""
    def has_missing(schema: dict) -> bool:
        for v in schema.values():
            if isinstance(v, dict) and not v.get("description"):
                return True
        return False

    inp = cap.get("input_schema", {}) or {}
    out = cap.get("output_schema", {}) or {}

    if not has_missing(inp) and not has_missing(out):
        return cap

    schema_json = json.dumps({"input_schema": inp, "output_schema": out}, indent=2)
    raw = _chat(
        client,
        ENRICH_PROMPT.format(name=cap["name"], skill=cap.get("skill", ""), schema_json=schema_json),
        system=ENRICH_SYSTEM,
        max_tokens=1500,
    )
    enriched = _parse_json(raw)
    if isinstance(enriched, dict):
        if "input_schema" in enriched:
            cap = {**cap, "input_schema": enriched["input_schema"]}
        if "output_schema" in enriched:
            cap = {**cap, "output_schema": enriched["output_schema"]}
    return cap


# ── Test case generation ──────────────────────────────────────────────────────

GENERATION_SYSTEM = """\
You are an expert at creating test cases for AI agent evaluation.

CRITICAL RULES:
- Use ONLY entity values (IDs, names, amounts, dates) from the DATABASE SNAPSHOT
- Do NOT invent any IDs, names, or values
- task_summary must start with "You are ..." (user-proxy perspective)
- arguments keys must EXACTLY match the parameter names in the input_schema — copy key names verbatim, never substitute synonyms (e.g. "reservation_id" not "booking_id", "flight_number" not "flight_id", "option" not "shipping_option", "content" not "message", "contents" not "text")
- arguments values must be exact values from the DB snapshot
- expected_output must be a realistic representation of what the tool returns, using DB values
- EXCEPTION: for tools that CREATE new entities (e.g. book_reservation, book_hotel, book_car_rental, create_booking), the newly generated ID does NOT exist in the snapshot yet. For those output fields (reservation_id, booking_id, rental_id, etc.), use a short natural-language phrase like "newly generated reservation ID" or "newly generated booking ID" — do NOT reuse an input entity ID (flight_id, hotel_id, car_id) as the output booking/reservation/rental ID
- subgoals are assertions about the AGENT's final response — what it said or did
- All subgoals must reference specific values from the DB snapshot"""

GENERATION_PROMPT = """\
Generate a test case for evaluating an AI agent executing this capability chain.

## Capability Chain
{chain_summary}

## Skill Definitions (for schema context)
{skill_definitions}

## Database Snapshot (ONLY source of real values)
{db_snapshot}

## Feasibility Note
{feasibility}

---

Generate a JSON object with this exact structure:

{{
  "task_summary": "You are [real name from DB, include their ID/account if relevant]. You want to [natural user request that requires ALL capabilities in this chain]. [2-3 sentences including relevant context with real values from DB].",

  "expected_capabilities": [
    {{
      "name": "<capability name>",
      "skill": "<skill name>",
      "description": "<capability description>",
      "input_schema": {{
        "<param>": {{"type": "<type>", "description": "<what it is>", "required": true|false}}
      }},
      "output_schema": {{
        "<field>": {{"type": "<type>", "description": "<what it returns>"}}
      }},
      "arguments": {{
        "<param>": <real value from DB snapshot>
      }},
      "expected_output": {{
        <realistic output using real DB values — keys MUST be taken verbatim from output_schema above, nothing else.
         EXCEPTION: for creation tools (book_reservation, book_hotel, book_car_rental, create_booking), use a natural-language phrase like "newly generated reservation ID" for the new entity ID — never reuse an input entity ID as the output ID.>
      }}
    }}
  ],

  "subgoals": [
    {{"description": "<one sentence assertion about what the AGENT must say or do, referencing real values>"}},
    ...
  ]
}}

Rules:
1. expected_capabilities must include ALL {n_caps} capabilities in the chain, in order
2. arguments must use ONLY values that appear in the DB snapshot
3. CRITICAL — argument keys must EXACTLY match the parameter names in the input_schema above — copy the key names verbatim (e.g. if input_schema has "reservation_id" the argument key MUST be "reservation_id", NOT "booking_id"; if input_schema has "option" the argument key MUST be "option", NOT "shipping_option")
4. CRITICAL — expected_output keys must EXACTLY match the field names defined in output_schema above — do NOT invent new field names, do NOT use synonyms (e.g. if output_schema has "certificate_id" use "certificate_id", NOT "user_id" or "amount"; if output_schema has "status" use "status", NOT "success")
5. expected_output values must be consistent with the DB snapshot values — EXCEPT for creation tools (book_reservation, book_hotel, book_car_rental, create_booking) where the new entity ID should be a natural-language phrase like "newly generated booking ID" since it does not exist yet
6. 3-5 subgoals, each a verifiable assertion about AGENT behavior (not DB facts)
7. Subgoals must reference specific IDs, names, or amounts from the DB snapshot

JSON Output:"""


def generate_testcase(
    chain: dict,
    graph_nodes: dict[str, dict],
    skill_defs: dict[str, dict],
    db_snapshot: dict,
    client: AzureOpenAI,
) -> dict | None:
    """
    Generate a grounded test case from a sampled chain + DB snapshot.

    Args:
        chain: sampled chain dict with 'chain' (node IDs) and 'capabilities' (names)
        graph_nodes: graph['nodes'] — node_id → {skill, name, description}
        skill_defs: skill_name → skill definition dict (from skill_extractor)
        db_snapshot: output from ClaudeDBSampler — {table: [rows], _feasibility, _file_artifacts}
        client: AzureOpenAI client

    Returns:
        Test case dict or None on failure.
    """
    # Build capability details with full schema from skill defs
    cap_details = []
    for node_id in chain["chain"]:
        info = graph_nodes.get(node_id, {})
        skill_name = info.get("skill", node_id.split(".")[0])
        cap_name = info.get("name", node_id.split(".", 1)[-1])
        description = info.get("description", "")

        # Get full schema from skill definition
        skill_def = skill_defs.get(skill_name, {})
        cap_def = next(
            (c for c in skill_def.get("capabilities", []) if c["name"] == cap_name),
            None,
        )

        cap = {
            "node_id": node_id,
            "skill": skill_name,
            "name": cap_name,
            "description": description or (cap_def.get("description", "") if cap_def else ""),
            "input_schema": (cap_def or {}).get("inputs", {}),
            "output_schema": (cap_def or {}).get("output_schema", {}),
        }

        # Ensure all schema fields have descriptions
        cap = _ensure_descriptions(cap, client)
        cap_details.append(cap)

    if not cap_details:
        return None

    # Build chain summary with descriptions and output schemas
    chain_lines = []
    for i, cap in enumerate(cap_details):
        out_keys = ", ".join(cap.get("output_schema", {}).keys())
        chain_lines.append(
            f"  {i+1}. {cap['skill']}.{cap['name']}: {cap['description']}\n"
            f"     output_schema fields: {out_keys or '(none)'}"
        )
    chain_summary = "\n".join(chain_lines)

    # Build skill definitions context (only relevant skills)
    skills_in_chain = list(dict.fromkeys(c["skill"] for c in cap_details))
    skill_def_lines = []
    for skill_name in skills_in_chain:
        sd = skill_defs.get(skill_name, {})
        if sd:
            skill_def_lines.append(f"### {skill_name}: {sd.get('description', '')}")
    skill_definitions = "\n".join(skill_def_lines) if skill_def_lines else "See capability descriptions above."

    # Clean snapshot (remove internal keys); fall back to workspace snapshot
    clean_snapshot = {k: v for k, v in db_snapshot.items() if not k.startswith("_")}
    if not clean_snapshot:
        clean_snapshot = db_snapshot.get("_workspace_snapshot", {})
    feasibility = db_snapshot.get("_feasibility", "")

    prompt = GENERATION_PROMPT.format(
        chain_summary=chain_summary,
        skill_definitions=skill_definitions,
        db_snapshot=json.dumps(clean_snapshot, indent=2, default=str),
        feasibility=feasibility,
        n_caps=len(cap_details),
    )

    raw = _chat(client, prompt, system=GENERATION_SYSTEM, max_tokens=4000)
    result = _parse_json(raw)

    if not isinstance(result, dict):
        print(f"    [gen] failed to parse LLM response")
        return None

    # Merge cap_details schema into expected_capabilities
    llm_caps = result.get("expected_capabilities", [])
    merged_caps = []
    for i, cap in enumerate(cap_details):
        llm_cap = llm_caps[i] if i < len(llm_caps) else {}
        merged_caps.append({
            "name": cap["name"],
            "skill": cap["skill"],
            "description": cap["description"],
            "input_schema": cap["input_schema"],
            "output_schema": cap["output_schema"],
            "arguments": llm_cap.get("arguments", {}),
            "expected_output": llm_cap.get("expected_output", {}),
        })

    file_artifacts = db_snapshot.get("_file_artifacts", [])
    workspace_snapshot = db_snapshot.get("_workspace_snapshot", {})
    subgoals = result.get("subgoals", [])

    # Enforce minimum 3 subgoals — retry generation if fewer returned
    if len(subgoals) < 3:
        retry_prompt = f"""The test case below has only {len(subgoals)} subgoal(s). Generate at least 3 subgoals.

Task: {result.get("task_summary", "")}
Capabilities: {chain_summary}
DB snapshot (abbreviated): {json.dumps({k: v[:1] for k, v in clean_snapshot.items()}, default=str)}

Return ONLY a JSON array of at least 3 subgoal objects:
[{{"description": "<assertion about agent behavior referencing real DB values>"}}, ...]"""
        retry_raw = _chat(client, retry_prompt, system=GENERATION_SYSTEM, max_tokens=800)
        retry_parsed = _parse_json(retry_raw)
        if isinstance(retry_parsed, list) and len(retry_parsed) >= 3:
            subgoals = retry_parsed

    return {
        "id": "tc_" + uuid.uuid4().hex[:8],
        "task_summary": result.get("task_summary", ""),
        "expected_capabilities": merged_caps,
        "subgoals": subgoals,
        # Metadata
        "_chain": chain["chain"],
        "_skills": chain["skills"],
        "_db_snapshot": clean_snapshot,
        "_workspace_snapshot": workspace_snapshot,
        "_file_artifacts": file_artifacts,
        "_feasibility": feasibility,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse, asyncio, sys
    sys.path.insert(0, str(Path(__file__).parent))
    from db_sampler import ClaudeDBSampler, _load_skill_contents

    parser = argparse.ArgumentParser(description="Generate test cases from capability chains + world.db")
    parser.add_argument("--db", required=True, help="Path to world.db")
    parser.add_argument("--graph", required=True, help="Path to graph.json")
    parser.add_argument("--defs-dir", required=True, help="Directory with skill definition JSONs")
    parser.add_argument("--skills-dir", required=True, help="Directory containing .cuga/skills-style SKILL.md dirs")
    parser.add_argument("--chains", required=True, help="Path to sampled_chains.json")
    parser.add_argument("--out", required=True, help="Output path for test_cases.json")
    parser.add_argument("--n", type=int, default=None, help="Max test cases to generate")
    parser.add_argument("--sampler-model", default="anthropic--claude-4.6-sonnet")
    parser.add_argument("--testbed", default=None, help="OfficeBench testbed path")
    parser.add_argument("--log-dir", default=None)
    args = parser.parse_args()

    db_path = Path(args.db)
    graph_file = Path(args.graph)
    defs_dir = Path(args.defs_dir)
    skills_dir = Path(args.skills_dir)
    chains_file = Path(args.chains)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    graph = json.load(open(graph_file))
    graph_nodes = graph["nodes"]
    chains = json.load(open(chains_file))
    if args.n:
        chains = chains[:args.n]

    # Load skill definitions
    skill_defs = {}
    for f in sorted(defs_dir.glob("*.json")):
        d = json.load(open(f))
        if isinstance(d, dict) and "name" in d and "capabilities" in d:
            skill_defs[d["name"]] = d
    print(f"Loaded {len(skill_defs)} skill definitions")

    client = make_client()
    sampler = ClaudeDBSampler(
        db_path=db_path,
        testbed_path=Path(args.testbed) if args.testbed else None,
        model=args.sampler_model,
        max_turns=30,
        log_dir=Path(args.log_dir) if args.log_dir else None,
    )

    async def run():
        test_cases = []
        for i, chain in enumerate(chains):
            caps = " → ".join(chain["capabilities"])
            print(f"\n[{i+1}/{len(chains)}] {caps}", flush=True)

            # Step 1: Sample real DB state
            print("  sampling DB...", flush=True)
            node_ids = chain["chain"]
            skills_in_chain = list(dict.fromkeys(
                graph_nodes.get(n, {}).get("skill", n.split(".")[0]) for n in node_ids
            ))
            skill_contents = _load_skill_contents(skills_dir, skills_in_chain)
            db_snapshot = await sampler.sample(node_ids, graph_nodes, skill_contents)

            if not db_snapshot:
                print("  ✗ No DB snapshot — skipping")
                continue

            tables = {k: len(v) for k, v in db_snapshot.items() if not k.startswith("_") and v}
            print(f"  snapshot: {tables}")

            # Step 2: Generate test case
            print("  generating...", flush=True)
            tc = generate_testcase(chain, graph_nodes, skill_defs, db_snapshot, client)
            if not tc:
                print("  ✗ Generation failed")
                continue

            test_cases.append(tc)
            print(f"  ✓ {tc['task_summary'][:80]}")
            print(f"    subgoals: {len(tc['subgoals'])}")

        with open(out_path, "w") as f:
            json.dump(test_cases, f, indent=2, ensure_ascii=False)
        print(f"\n{len(test_cases)} test cases → {out_path}")

        # Print summary
        print(f"\n{'='*65}")
        for tc in test_cases:
            print(f"  [{tc['id']}] {tc['task_summary'][:70]}")
            for sg in tc['subgoals']:
                print(f"    • {sg['description'][:70]}")
        print(f"{'='*65}")

    asyncio.run(run())


if __name__ == "__main__":
    main()
