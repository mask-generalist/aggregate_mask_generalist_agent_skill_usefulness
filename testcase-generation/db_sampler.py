"""Claude Code-based DB sampler for the multi-skill mock system.

Given a sampled capability chain (from the graph) and the SKILL.md content
for each involved skill, spawns Claude Code to query world.db read-only and
return a self-consistent snapshot of real entities that make the chain executable.

Claude has full read access — it writes its own SQL/grep/sqlite3 queries.
No invocation patterns, no violated subgoals, no synthetic scenario context.

Usage (standalone):
    python db_sampler.py \\
        --db   multi_skill_mock_system/generated/db/world.db \\
        --graph testcase_synthesis/skill_definitions/graph.json \\
        --defs  testcase_synthesis/skill_definitions \\
        --chain "OfficeBench.excel_read_file,state-customer-support.process_return" \\
        --out   /tmp/sample_out.json
"""

import asyncio
import json
import logging
import sqlite3
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────────────────────

SAMPLER_PROMPT = """\
You are sampling database state for a capability chain test scenario.

## Capability Chain
{capability_chain}

## Skill Definitions (for understanding only — NOT a data source)
The skill definitions below describe what each capability does and what inputs/outputs it expects.
Use them ONLY to understand what entities and fields each step needs.
Do NOT use any example IDs, seed data, customer lists, or db.json references from these definitions.
The ONLY source of real data is world.db.

{skill_definitions}

## Database Schema
{db_schema}

## CRITICAL: world.db is the ONLY data source
- Path: {db_path}
- All entity IDs (users, orders, bookings, products, etc.) MUST come from querying this database
- Do NOT use IDs, names, or data from skill definitions, SKILL.md examples, or seed files
- Use SELECT queries only: sqlite3 "file:{db_path}?mode=ro" "SELECT ..."
- Do NOT read any .json, .md, or other files — only query world.db

## Available File Artifacts (from world.db)
{file_artifacts}

## Your Task
Query world.db to find a real, self-consistent set of entities that makes this capability chain executable end-to-end.

Steps:
1. Run SELECT queries to discover what entities exist in world.db for the tables this chain needs
2. Find entities whose state makes the chain feasible (e.g. a confirmed order for process_return, a user with payment methods for booking)
3. Retrieve all related rows via JOINs following FK relationships
4. Verify the chain is actually executable with these real entities
5. If no suitable entity exists in world.db, output {{"error": "no_suitable_entity", "reason": "<why>"}}

Output:
Write a single JSON object to `{output_path}` with:
- `"<table_name>": [{{row_dict}}, ...]` for every relevant table (use column names from schema)
- `"_feasibility"`: plain-language summary of what was found in world.db and what the chain can do
- `"_file_artifacts"`: list of {{"path": "...", "type": "excel|word|email"}} for any files involved ([] if none)

All entity IDs in the output MUST be verifiable by running: sqlite3 "{db_path}" "SELECT * FROM <table> WHERE <id_col>=<value>"
"""

WORKSPACE_SAMPLER_PROMPT = """\
You are sampling workspace file state for a capability chain test scenario.

## Capability Chain
{capability_chain}

## Skill Definitions
{skill_definitions}

## Workspace Directory
Your current working directory is the workspace: {workspace_path}

The workspace contains these files:
{file_artifacts}

## Your Task
Read the workspace files to find real, self-consistent content that makes this capability chain executable.

Steps:
1. Use Bash to list and read workspace files relevant to this chain (e.g. `cat data/sales_q3.csv`, `cat data/employees.json`)
2. Extract specific real values (file paths, field values, row content) that ground this chain concretely
3. Verify the chain is executable with this real content

Output:
Write a single JSON object to `{output_path}` with:
- `"_feasibility"`: plain-language summary of what files exist and what the chain can do with them
- `"_file_artifacts"`: list of {{"path": "<relative path>", "type": "csv|json|markdown|text|yaml|python"}} for files involved
- `"_workspace_snapshot"`: dict of {{"<relative_file_path>": "<first 500 chars of content>"}} for key files in the chain
"""


# ── Schema loader ─────────────────────────────────────────────────────────────

def _load_schema(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
    ).fetchall()
    conn.close()
    return "\n\n".join(r[0] for r in rows)


# ── File artifact lister ──────────────────────────────────────────────────────

def _list_file_artifacts(db_path: Path | None, testbed_path: Path | None) -> str:
    lines = []

    # From DB tables
    if db_path:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT file_path FROM ob_excel_files").fetchall()
            for r in rows:
                lines.append(f"  [excel] {r[0]}")
            rows = conn.execute("SELECT file_path FROM ob_word_documents").fetchall()
            for r in rows:
                lines.append(f"  [word]  {r[0]}")
        except Exception:
            pass
        conn.close()

    # From testbed disk
    if testbed_path and testbed_path.exists():
        for subdir in ["data", "docs", "emails", "images"]:
            d = testbed_path / subdir
            if d.exists():
                for f in sorted(d.iterdir()):
                    lines.append(f"  [{subdir}] {testbed_path}/{subdir}/{f.name}")

    return "\n".join(lines) if lines else "  (none)"


# ── Skill definition formatter ────────────────────────────────────────────────

def _format_skill_definitions(
    chain_nodes: list[str],
    graph_nodes: dict[str, dict],
    skill_contents: dict[str, str],
) -> str:
    """
    For each skill involved in the chain, include:
    - The SKILL.md content (so Claude understands what each tool needs)
    - A focused list of the capabilities in this chain with their descriptions
    """
    # Group chain nodes by skill
    skills_in_chain: dict[str, list[dict]] = {}
    for node_id in chain_nodes:
        info = graph_nodes.get(node_id, {})
        skill = info.get("skill", node_id.split(".")[0])
        if skill not in skills_in_chain:
            skills_in_chain[skill] = []
        skills_in_chain[skill].append({
            "node_id": node_id,
            "name": info.get("name", node_id.split(".", 1)[-1]),
            "description": info.get("description", ""),
        })

    parts = []
    for skill, caps in skills_in_chain.items():
        part = [f"### {skill}"]

        # Capabilities in this chain
        part.append("Capabilities used in this chain:")
        for c in caps:
            part.append(f"  - {c['name']}: {c['description']}")

        # Full SKILL.md if available
        if skill in skill_contents:
            part.append("")
            part.append("Full skill definition (SKILL.md):")
            part.append(skill_contents[skill])

        parts.append("\n".join(part))

    return "\n\n---\n\n".join(parts)


def _format_chain(chain_nodes: list[str], graph_nodes: dict[str, dict]) -> str:
    steps = []
    for node_id in chain_nodes:
        info = graph_nodes.get(node_id, {})
        name = info.get("name", node_id.split(".", 1)[-1])
        skill = info.get("skill", node_id.split(".")[0])
        desc = info.get("description", "")
        steps.append(f"  {skill}.{name}: {desc}" if desc else f"  {skill}.{name}")
    return "\n".join(steps)


# ── Main sampler ──────────────────────────────────────────────────────────────

class ClaudeDBSampler:
    """
    Invokes Claude Code to sample real DB entities for a capability chain.

    Args:
        db_path: Path to world.db (optional — omit for workspace-only scenarios)
        testbed_path: Optional path to OfficeBench testbed (for file artifact listing)
        workspace_path: Optional path to workspace dir (for file-based skills)
        model: Claude model identifier
        max_turns: Max Claude Code turns
        log_dir: Optional directory to save Claude Code logs
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        testbed_path: str | Path | None = None,
        workspace_path: str | Path | None = None,
        model: str = "anthropic--claude-4.6-opus[1m]",
        max_turns: int = 35,
        log_dir: str | Path | None = None,
    ):
        self.db_path = Path(db_path) if db_path else None
        self.testbed_path = Path(testbed_path) if testbed_path else None
        self.workspace_path = Path(workspace_path) if workspace_path else None
        self.model = model
        self.max_turns = max_turns
        self.log_dir = Path(log_dir) if log_dir else None
        self._call_count = 0
        self._db_schema = _load_schema(self.db_path) if self.db_path else ""

    async def sample(
        self,
        chain_nodes: list[str],
        graph_nodes: dict[str, dict],
        skill_contents: dict[str, str],
    ) -> dict:
        """
        Sample DB state for a capability chain.

        Args:
            chain_nodes: Ordered list of node IDs from the graph (e.g. ["state-shopping.get_cart", ...])
            graph_nodes: The full graph nodes dict (node_id → {skill, name, description})
            skill_contents: Dict of skill_name → SKILL.md text for skills in this chain

        Returns:
            Dict with table_name → [row_dicts], plus "_feasibility" and "_file_artifacts".
            Empty dict if sampling failed or no suitable entity found.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="db_sample_"
        ) as f:
            output_path = f.name

        capability_chain = _format_chain(chain_nodes, graph_nodes)
        skill_definitions = _format_skill_definitions(chain_nodes, graph_nodes, skill_contents)
        file_artifacts = _list_file_artifacts(self.db_path, self.testbed_path or self.workspace_path)

        if self.workspace_path and not self.db_path:
            # Workspace-only scenario (no DB) — sample from files
            prompt = WORKSPACE_SAMPLER_PROMPT.format(
                capability_chain=capability_chain,
                skill_definitions=skill_definitions,
                workspace_path=str(self.workspace_path),
                file_artifacts=file_artifacts,
                output_path=output_path,
            )
            cwd = str(self.workspace_path)
        elif self.db_path:
            # DB scenario (possibly with workspace) — world.db is the primary data source
            prompt = SAMPLER_PROMPT.format(
                capability_chain=capability_chain,
                skill_definitions=skill_definitions,
                db_schema=self._db_schema,
                db_path=str(self.db_path),
                file_artifacts=file_artifacts,
                output_path=output_path,
            )
            cwd = str(self.db_path.parent)
        else:
            logger.warning("No db_path or workspace_path — cannot sample")
            return {}

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude",
                "--print",
                "--permission-mode", "auto",
                "--model", self.model,
                "--max-turns", str(self.max_turns),
                "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                logger.warning("Claude DB sampler timed out")
                return {}

            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""

            self._call_count += 1
            if self.log_dir:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                log_file = self.log_dir / f"sampler_{self._call_count:03d}.log"
                with open(log_file, "w") as lf:
                    lf.write(f"=== Chain ===\n{capability_chain}\n\n")
                    lf.write(f"=== Prompt ===\n{prompt}\n\n")
                    lf.write(f"=== RC: {proc.returncode} ===\n\n")
                    lf.write(f"=== Stdout ===\n{stdout_str}\n\n")
                    lf.write(f"=== Stderr ===\n{stderr_str}\n")

            if proc.returncode != 0:
                logger.warning(f"Claude DB sampler failed (rc={proc.returncode}): {stderr_str[:300]}")
                return {}

            out_file = Path(output_path)
            if out_file.exists():
                with open(out_file) as f:
                    data = json.load(f)
                if "error" in data:
                    logger.info(f"No suitable entity: {data.get('reason', '')}")
                    return {}
                return data
            else:
                logger.warning("Claude DB sampler produced no output file")
                return {}

        except Exception as e:
            logger.error(f"Claude DB sampler error: {e}")
            return {}
        finally:
            Path(output_path).unlink(missing_ok=True)


# ── Standalone runner ─────────────────────────────────────────────────────────

def _load_skill_contents(skills_dir: Path, skill_names: list[str]) -> dict[str, str]:
    contents = {}
    for name in skill_names:
        skill_md = skills_dir / name / "SKILL.md"
        if skill_md.exists():
            contents[name] = skill_md.read_text()
    return contents


async def _run_standalone(args):
    db_path = Path(args.db)
    graph_file = Path(args.graph)
    defs_dir = Path(args.defs)
    chain_node_ids = [n.strip() for n in args.chain.split(",")]
    out_path = Path(args.out) if args.out else None

    # Load graph nodes
    with open(graph_file) as f:
        graph = json.load(f)
    graph_nodes = graph["nodes"]

    # Load SKILL.md for skills in chain
    skills_in_chain = list(dict.fromkeys(
        graph_nodes.get(n, {}).get("skill", n.split(".")[0])
        for n in chain_node_ids
    ))
    # defs_dir is testcase_synthesis/skill_definitions; SKILL.md files are in .cuga/skills/
    skills_dir = defs_dir.parent.parent / ".cuga" / "skills"
    skill_contents = _load_skill_contents(skills_dir, skills_in_chain)

    print(f"Chain: {' → '.join(chain_node_ids)}")
    print(f"Skills: {', '.join(skills_in_chain)}")
    print(f"SKILL.md loaded: {list(skill_contents.keys())}")
    print(f"DB: {db_path}\n")

    sampler = ClaudeDBSampler(
        db_path=db_path,
        testbed_path=db_path.parent.parent.parent / ".cuga" / "skills" / "OfficeBench" / "testbed",
        model=args.model,
        max_turns=args.max_turns,
        log_dir=Path(args.log_dir) if args.log_dir else None,
    )

    result = await sampler.sample(chain_node_ids, graph_nodes, skill_contents)

    if not result:
        print("No result — no suitable entity found or sampler failed.")
        return

    if out_path:
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Snapshot written to {out_path}")
    else:
        print(json.dumps(result, indent=2))

    print(f"\n_feasibility: {result.get('_feasibility', '')}")
    print(f"_file_artifacts: {result.get('_file_artifacts', [])}")
    tables = [k for k in result if not k.startswith("_")]
    print(f"Tables: {tables}")
    for t in tables:
        print(f"  {t}: {len(result[t])} rows")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Claude Code DB sampler for multi-skill world.db")
    parser.add_argument("--db", required=True, help="Path to world.db")
    parser.add_argument("--graph", required=True, help="Path to graph.json")
    parser.add_argument("--defs", required=True, help="Path to skill_definitions dir")
    parser.add_argument("--chain", required=True,
                        help="Comma-separated node IDs, e.g. 'state-shopping.get_cart,state-customer-support.process_return'")
    parser.add_argument("--out", default=None, help="Output JSON path (default: print to stdout)")
    parser.add_argument("--model", default="anthropic--claude-4.6-opus[1m]")
    parser.add_argument("--max-turns", type=int, default=35)
    parser.add_argument("--log-dir", default=None, help="Directory to save Claude Code logs")
    args = parser.parse_args()

    asyncio.run(_run_standalone(args))


if __name__ == "__main__":
    main()
