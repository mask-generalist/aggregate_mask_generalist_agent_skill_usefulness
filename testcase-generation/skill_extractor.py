"""Extract SkillDefinition JSON from .cuga/skills/*/SKILL.md using Claude.

Spawns one Claude CLI subprocess per skill folder so each extraction gets
a clean context.  Claude reads all files in the skill directory and produces
a structured JSON definition expected by graph.py and testcase_gen.py.

Usage:
    python skill_extractor.py [--skills-dir <path>] [--out-dir <path>]
                              [--skills skill1 skill2 ...]
                              [--model anthropic--claude-4.6-opus[1m]]
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).parent
_SKILLS_DIR = _HERE.parent / ".cuga" / "skills"
_OUT_DIR = _HERE / "skill_definitions"

DEFAULT_MODEL = "anthropic--claude-4.6-opus[1m]"

EXTRACTION_PROMPT = """\
Read every file in this directory (SKILL.md, policies.md, any other docs)
and extract a structured skill definition.

Return ONLY valid JSON — no prose before or after. No markdown fences.

The JSON must have this exact structure:
{{
  "name": "<skill name from SKILL.md frontmatter>",
  "description": "<one-sentence skill description>",
  "capabilities": [
    {{
      "name": "<tool/capability name — snake_case matching the tool name in SKILL.md>",
      "description": "<what this capability does>",
      "inputs": {{
        "<param_name>": {{"type": "<string|integer|boolean|array|object>", "description": "<what it is>", "required": true|false}}
      }},
      "output_schema": {{
        "<field>": {{"type": "<type>", "description": "<what it returns>"}}
      }},
      "invocation_pattern": "<how to call it, e.g. tools.get_order('<order_id>')>"
    }}
  ],
  "flows": [
    {{
      "name": "<flow name — a realistic multi-step user task>",
      "steps": ["<capability_name_1>", "<capability_name_2>", ...]
    }}
  ]
}}

CRITICAL — name and ID fidelity:
- capability names must EXACTLY match the tool/function names as written in SKILL.md — do not rename, re-case, or paraphrase them
- Parameter names in "inputs" must EXACTLY match the parameter names shown in the tool signature or parameter table in SKILL.md — copy them verbatim, do not substitute synonyms (e.g. if SKILL.md says "reservation_id" do NOT write "booking_id"; if it says "flight_number" do NOT write "flight_id")
- Output field names must also match the documented return fields exactly
- If a tool uses "cabin" do not write "cabin_class"; if it uses "option" do not write "shipping_option"

Other rules:
- Extract ONE capability per distinct tool/command listed in SKILL.md
- Do NOT include capabilities that are not listed as tools in SKILL.md
- For inputs: include EVERY parameter the tool accepts, with correct types and required flags — do not omit optional parameters
- For output_schema: describe the shape of what the tool returns
- Make 2-4 flows representing realistic multi-step user tasks for this skill
- Respond with ONLY the JSON object, nothing else
"""


def _parse_json(raw: str) -> dict | None:
    """Extract JSON from raw text, handling code fences and preamble."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    idx = raw.find("{")
    if idx > 0:
        raw = raw[idx:]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return None


async def extract_skill(
    skill_dir: Path,
    model: str = DEFAULT_MODEL,
    max_turns: int = 15,
) -> dict | None:
    """Extract a skill definition by spawning a Claude subprocess in skill_dir."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix=f"skill_{skill_dir.name}_"
    ) as f:
        output_path = f.name

    prompt = (
        EXTRACTION_PROMPT
        + f"\n\nWrite the JSON result to: {output_path}"
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--print", "--permission-mode", "auto",
            "--model", model,
            "--max-turns", str(max_turns),
            "-p", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(skill_dir),
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=300
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            print(f"    ✗ Timed out for {skill_dir.name}")
            return None

        # Check the output file first — Claude may have written it even if
        # it hit max-turns (rc=1) afterward.
        out_file = Path(output_path)
        if out_file.exists():
            try:
                result = json.load(open(out_file))
                if isinstance(result, dict) and "name" in result and "capabilities" in result:
                    result["skill_path"] = str(skill_dir)
                    return result
            except json.JSONDecodeError:
                pass

        # Fall back to parsing stdout
        raw = stdout.decode() if stdout else ""
        result = _parse_json(raw)
        if isinstance(result, dict) and "name" in result and "capabilities" in result:
            result["skill_path"] = str(skill_dir)
            return result

        if proc.returncode != 0:
            print(f"    ✗ Claude exited with rc={proc.returncode} for {skill_dir.name}")
            stderr_text = stderr.decode()[:500] if stderr else ""
            if stderr_text:
                print(f"      stderr: {stderr_text}")
        else:
            print(f"    ✗ Failed to parse output for {skill_dir.name}")
        return None

    except Exception as e:
        print(f"    ✗ Error extracting {skill_dir.name}: {e}")
        return None
    finally:
        Path(output_path).unlink(missing_ok=True)


async def run(skills_dir: Path, out_dir: Path, skill_names: list[str] | None, model: str):
    out_dir.mkdir(parents=True, exist_ok=True)

    skill_dirs = sorted(
        d for d in skills_dir.iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )
    if skill_names:
        skill_dirs = [d for d in skill_dirs if d.name in skill_names]

    if not skill_dirs:
        print(f"No skill directories found in {skills_dir}")
        sys.exit(1)

    print(f"Extracting {len(skill_dirs)} skills from {skills_dir}")
    print(f"Model: {model}\n")

    for skill_dir in skill_dirs:
        print(f"  {skill_dir.name}...", end=" ", flush=True)
        defn = await extract_skill(skill_dir, model=model)
        if defn:
            out_file = out_dir / f"{skill_dir.name}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(defn, f, indent=2, ensure_ascii=False)
            caps = len(defn.get("capabilities", []))
            flows = len(defn.get("flows", []))
            print(f"✓ {caps} capabilities, {flows} flows → {out_file.name}")
        else:
            print("✗ skipped")

    print(f"\nDone. Definitions in {out_dir}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract skill definitions using Claude")
    parser.add_argument("--skills-dir", default=str(_SKILLS_DIR))
    parser.add_argument("--out-dir", default=str(_OUT_DIR))
    parser.add_argument("--skills", nargs="*", help="Specific skill names to extract (default: all)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    asyncio.run(run(
        skills_dir=Path(args.skills_dir),
        out_dir=Path(args.out_dir),
        skill_names=args.skills,
        model=args.model,
    ))


if __name__ == "__main__":
    main()
