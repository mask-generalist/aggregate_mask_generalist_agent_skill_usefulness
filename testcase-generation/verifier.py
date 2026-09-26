"""
Test case consistency verifier.

Checks that the generated test case (expected_capabilities.arguments,
expected_output, subgoals) is consistent with the sampled DB snapshot.
No hallucinated values — every ID and factual claim must be traceable
to the snapshot rows.

Spawns Claude Code read-only against world.db to cross-check and fix.
Returns the original (valid), a corrected version (fixed), or rejects
if the scenario is fundamentally infeasible.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


VERIFY_PROMPT = """\
You are verifying that a generated test case is consistent with the sampled environment snapshot.

## Test Case
```json
{test_case_json}
```

## Sampled Snapshot (source of truth)
```json
{snapshot_json}
```

## Environment Access
{env_access}

## Your job
Check whether all values in expected_capabilities and subgoals are consistent
with the snapshot above.{db_query_instruction}

### What to check:
1. **Argument grounding** — every ID and value in expected_capabilities[].arguments
   must appear in the snapshot rows (user_id, order_id, item_id, product_id,
   booking_id, cart_id, username, file_path, etc.)
2. **Expected output consistency** — expected_output values must match what the
   snapshot rows contain (e.g. prices, statuses, names from the snapshot)
3. **Subgoal factual accuracy** — each subgoal assertion must reference values
   that actually appear in the snapshot (real IDs, real prices, real names)
4. **No invented values** — if any argument or subgoal references an ID/value
   not in the snapshot, it is a hallucination and must be fixed

### Output format — write JSON to `{output_path}`:

If the test case is CORRECT:
{{"status": "valid", "fixed_test_case": null, "issues_found": []}}

If issues found and fixable:
{{
  "status": "fixed",
  "issues_found": ["<description of each issue>"],
  "fixed_test_case": {{
    "id": "<same id>",
    "task_summary": "<corrected if needed>",
    "expected_capabilities": [
      {{
        "name": "<capability name>",
        "skill": "<skill>",
        "description": "<description>",
        "input_schema": {{...unchanged...}},
        "output_schema": {{...unchanged...}},
        "arguments": {{<corrected using snapshot values only>}},
        "expected_output": {{<corrected using snapshot values>}}
      }}
    ],
    "subgoals": [{{"description": "<corrected assertion using real snapshot values>"}}]
  }}
}}

If fundamentally infeasible (snapshot has no suitable data for this scenario):
{{"status": "rejected", "issues_found": ["<reason>"], "fixed_test_case": null}}

IMPORTANT: Use ONLY values from the snapshot when fixing. Never invent IDs or values.
"""


class ConsistencyVerifier:
    """
    Verify that a generated test case is consistent with its environment snapshot.

    Uses Claude Code to cross-check arguments, expected outputs, and subgoal
    assertions against the sampled rows/files. Fixes hallucinated values in-place.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        testbed_path: Path | None = None,
        workspace_path: Path | None = None,
        model: str = "anthropic--claude-4.6-opus[1m]",
        max_turns: int = 35,
        log_dir: Path | None = None,
    ):
        self.db_path = Path(db_path) if db_path else None
        self.testbed_path = Path(testbed_path) if testbed_path else None
        self.workspace_path = Path(workspace_path) if workspace_path else None
        self.model = model
        self.max_turns = max_turns
        self.log_dir = Path(log_dir) if log_dir else None
        self._call_count = 0

    async def verify_and_fix(
        self, tc: dict
    ) -> tuple[str, dict | None, list[str]]:
        """
        Check test case consistency with its _db_snapshot.

        Returns:
            (status, fixed_tc_or_None, issues)
            status: "valid" | "fixed" | "rejected"
        """
        snapshot = tc.get("_db_snapshot", {})
        workspace_snapshot = tc.get("_workspace_snapshot", {})
        combined_snapshot = {**snapshot, **({'_workspace_snapshot': workspace_snapshot} if workspace_snapshot else {})}
        if not snapshot and not workspace_snapshot:
            logger.warning("No snapshot in test case — skipping verification")
            return "valid", None, []

        # Build env_access and db_query_instruction based on what's available
        env_parts = []
        db_query_instruction = ""
        if self.db_path:
            env_parts.append(f"Database: {self.db_path}")
            db_query_instruction = f"\nUse SELECT queries on the DB if you need additional context not in the snapshot: sqlite3 \"file:{self.db_path}?mode=ro\" \"SELECT ...\""
        if self.testbed_path:
            env_parts.append(f"Testbed: {self.testbed_path}")
        if self.workspace_path:
            env_parts.append(f"Workspace: {self.workspace_path}")
        env_access = "\n".join(env_parts) if env_parts else "(snapshot only)"

        # Determine cwd for Claude Code
        if self.workspace_path:
            cwd = str(self.workspace_path)
        elif self.db_path:
            cwd = str(self.db_path.parent)
        else:
            cwd = str(Path.cwd())

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="cv_out_"
        ) as f:
            output_path = f.name

        prompt = VERIFY_PROMPT.format(
            test_case_json=json.dumps(
                {k: v for k, v in tc.items() if not k.startswith("_")},
                indent=2, default=str
            ),
            snapshot_json=json.dumps(combined_snapshot, indent=2, default=str),
            env_access=env_access,
            db_query_instruction=db_query_instruction,
            output_path=output_path,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "--print", "--permission-mode", "auto",
                "--model", self.model,
                "--max-turns", str(self.max_turns),
                "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=300
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                logger.warning("Consistency verifier timed out")
                return "valid", None, []

            self._call_count += 1
            if self.log_dir:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                log_file = self.log_dir / f"verifier_{self._call_count:03d}.log"
                with open(log_file, "w") as lf:
                    lf.write(f"=== TC id={tc.get('id')} ===\n\n")
                    lf.write(f"=== RC: {proc.returncode} ===\n\n")
                    lf.write(f"=== Stdout ===\n{stdout.decode()}\n\n")
                    lf.write(f"=== Stderr ===\n{stderr.decode()}\n")

            if proc.returncode != 0:
                logger.warning(f"Consistency verifier failed rc={proc.returncode}")
                return "valid", None, []

            out_file = Path(output_path)
            if out_file.exists():
                data = json.load(open(out_file))
                out_file.unlink()
                return self._parse(data, tc)
            else:
                logger.warning("Consistency verifier produced no output file")
                return "valid", None, []

        except Exception as e:
            logger.error(f"Consistency verifier error: {e}")
            return "valid", None, []
        finally:
            Path(output_path).unlink(missing_ok=True)

    def _parse(
        self, data: dict, original: dict
    ) -> tuple[str, dict | None, list[str]]:
        status = data.get("status", "valid")
        issues = data.get("issues_found", [])

        if status == "valid":
            return "valid", None, []

        if status == "rejected":
            return "rejected", None, issues

        if status == "fixed":
            fixed = data.get("fixed_test_case")
            if not fixed:
                return "valid", None, []
            # Merge corrected fields back, preserving metadata (_db_snapshot etc.)
            merged = {**original, **fixed}
            merged["_verification_status"] = "fixed"
            merged["_verification_issues"] = issues
            return "fixed", merged, issues

        return "valid", None, []
