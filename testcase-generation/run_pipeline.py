#!/usr/bin/env python3
"""
Testcase synthesis pipeline — skill-set controlled.

T_old: generate test cases for an explicitly defined set of skills.
T_new: generate test cases for chains that involve at least one new skill
       (new skills are added on top of the T_old base set).

Usage (from SkillEvaluation root):
    export AZURE_API_KEY=... AZURE_API_VERSION=... AZURE_API_BASE=...

    # T_old — 5 base skills, 10 test cases
    python testcase_synthesis/run_pipeline.py \\
        --skills tau2Airline state-shopping state-customer-support toolsandbox-assistant OfficeBench \\
        --out testcase_synthesis/told/output/test_cases.json \\
        --n 10

    # T_new — add state-travel, only chains that touch it
    python testcase_synthesis/run_pipeline.py \\
        --skills tau2Airline state-shopping state-customer-support toolsandbox-assistant OfficeBench \\
        --new-skills state-travel \\
        --out testcase_synthesis/tnew/output/test_cases.json \\
        --n 10

    # Resume from sample step (graph already built):
    python testcase_synthesis/run_pipeline.py ... --from-step sample

    # Resume from generate step only:
    python testcase_synthesis/run_pipeline.py ... --from-step generate
"""
import argparse, asyncio, json, os, shutil, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
TS = ROOT / "testcase_synthesis"
CUGA = ROOT / "CUGA_generalist_agent"

sys.path.insert(0, str(TS))

from graph import build_graph, add_cross_skill_edges
from sampler import sample_chains, load_graph
from testcase_gen import generate_testcase, make_client
from db_sampler import ClaudeDBSampler, _load_skill_contents
from verifier import ConsistencyVerifier
from convert_to_yaml import convert as convert_tc_to_yaml

DB_PATH = CUGA / "multi_skill_mock_system" / "generated" / "db" / "world.db"
SKILLS_DIR = CUGA / ".cuga" / "skills"
TESTBED = CUGA / ".cuga" / "skills" / "OfficeBench" / "testbed"

# These can be overridden via CLI args --db / --skills-dir / --testbed
_db_path_override: Path | None = None
_skills_dir_override: Path | None = None
_testbed_override: Path | None = None
_workspace_override: Path | None = None
GLOBAL_DEFS = TS / "skill_definitions"   # pre-extracted skill JSONs


# ── Verification ──────────────────────────────────────────────────────────────
# Two-stage verification is handled by verifier.py (imported above).
# See step_generate() for how ExecutionVerifier + ClaudeVerifier are called.


# ── Pipeline steps ────────────────────────────────────────────────────────────

def step_graph(defs_dir: Path, skills: list[str]) -> Path:
    print(f'\n--- Step 1: Build capability graph ({len(skills)} skills) ---')
    definition_files = [defs_dir / f'{s}.json' for s in skills if (defs_dir / f'{s}.json').exists()]
    missing = [s for s in skills if not (defs_dir / f'{s}.json').exists()]
    if missing:
        print(f'  WARNING: skill definitions not found: {missing}')
        print(f'  Run skill_extractor.py first for those skills.')
    print(f'  Loading: {[f.stem for f in definition_files]}')

    graph = build_graph(definition_files)
    skill_names = set(n['skill'] for n in graph.nodes.values())
    print(f'  Nodes: {len(graph.nodes)} capabilities across {len(skill_names)} skills')
    print(f'  Within-skill edges: {len(graph.edges)}')
    print('  Adding cross-skill edges via LLM...')
    before = len(graph.edges)
    add_cross_skill_edges(graph)
    print(f'  Cross-skill edges added: {len(graph.edges) - before}')

    graph_file = defs_dir / 'graph.json'
    with open(graph_file, 'w') as f:
        json.dump(graph.to_dict(), f, indent=2)
    print(f'  → {graph_file}')
    return graph_file


def step_sample(
    defs_dir: Path,
    n: int = 20,
    new_skills: list[str] | None = None,
    chain_type: str = 'all',
    cross_skill_only: bool = False,
) -> Path:
    graph_file = defs_dir / 'graph.json'
    print(f'\n--- Step 2: Sample chains (n={n}, type={chain_type}, cross_skill_only={cross_skill_only}) ---')
    graph = load_graph(graph_file)

    # Sample generously when filtering is needed
    sample_n = n * 10 if (new_skills or cross_skill_only) else n
    all_chains = sample_chains(graph, n=sample_n, chain_type=chain_type)

    chains = all_chains
    if new_skills:
        print(f'  Filtering for chains involving new skills: {new_skills}')
        chains = [c for c in chains if any(s in new_skills for s in c['skills'])]
        print(f'  Found {len(chains)} chains touching new skills (from {len(all_chains)} sampled)')
    if cross_skill_only:
        before = len(chains)
        chains = [c for c in chains if len(set(c['skills'])) > 1]
        print(f'  Filtered to cross-skill only: {len(chains)} (from {before})')

    chains = chains[:n]
    if len(chains) < n:
        print(f'  WARNING: only {len(chains)} chains available after filtering')

    print(f'  Sampled {len(chains)} chains:')
    for i, c in enumerate(chains):
        print(f'    [{i+1}] {" → ".join(c["capabilities"][:3])}{"..." if len(c["capabilities"])>3 else ""} [{",".join(c["skills"])}]')

    chains_file = defs_dir / 'sampled_chains.json'
    with open(chains_file, 'w') as f:
        json.dump(chains, f, indent=2)
    print(f'  → {chains_file}')
    return chains_file


async def step_generate(
    defs_dir: Path,
    out_file: Path,
    log_dir: Path,
    n: int = 10,
    sampler_model: str = 'anthropic--claude-4.6-sonnet',
    all_skills: list[str] | None = None,
) -> list[dict]:
    chains_file = defs_dir / 'sampled_chains.json'
    graph_file = defs_dir / 'graph.json'
    print(f'\n--- Step 3: Generate {n} test cases ---')

    with open(chains_file) as f:
        chains = json.load(f)[:n]
    with open(graph_file) as f:
        graph = json.load(f)
    graph_nodes = graph['nodes']

    # Load skill definitions
    skill_defs = {}
    for f in sorted(defs_dir.glob('*.json')):
        if f.name in ('graph.json', 'sampled_chains.json'):
            continue
        d = json.load(open(f))
        if isinstance(d, dict) and 'name' in d and 'capabilities' in d:
            skill_defs[d['name']] = d
    print(f'  Skill defs: {list(skill_defs.keys())}')

    db_path = _db_path_override  # None when --db not provided (workspace-only scenarios)
    skills_dir = _skills_dir_override or SKILLS_DIR
    testbed = _testbed_override
    workspace = _workspace_override

    client = make_client()
    sampler = ClaudeDBSampler(
        db_path=db_path,
        testbed_path=testbed,
        workspace_path=workspace,
        model=sampler_model,
        max_turns=35,
        log_dir=log_dir,
    )
    verifier = ConsistencyVerifier(
        db_path=db_path,
        testbed_path=testbed,
        workspace_path=workspace,
        model=sampler_model,
        max_turns=35,
        log_dir=log_dir,
    )

    test_cases = []
    stats = {'valid': 0, 'fixed': 0, 'rejected': 0}

    for i, chain in enumerate(chains):
        caps = ' → '.join(chain['capabilities'])
        print(f'\n  [{i+1}/{len(chains)}] {caps}', flush=True)

        node_ids = chain['chain']
        skills_in_chain = list(dict.fromkeys(
            graph_nodes.get(nd, {}).get('skill', nd.split('.')[0]) for nd in node_ids
        ))
        skill_contents = _load_skill_contents(skills_dir, skills_in_chain)

        # DB sampling
        print('    sampling DB...', flush=True)
        db_snapshot = await sampler.sample(node_ids, graph_nodes, skill_contents)
        if not db_snapshot:
            print('    ✗ No DB snapshot — skipping')
            continue
        tables = {k: len(v) for k, v in db_snapshot.items() if not k.startswith('_') and v}
        print(f'    snapshot: {tables}')

        # Generation
        print('    generating...', flush=True)
        tc = generate_testcase(chain, graph_nodes, skill_defs, db_snapshot, client)
        if not tc:
            print('    ✗ Generation failed')
            continue

        # Consistency verification
        print('    verifying consistency with snapshot...', flush=True)
        status, fixed_tc, issues = await verifier.verify_and_fix(tc)
        if status == 'valid':
            print('    ✓ Consistent — no hallucinations detected')
            tc['_verification_status'] = 'valid'
            tc['_verification_issues'] = []
            stats['valid'] += 1
        elif status == 'fixed':
            print(f'    ✓ Fixed {len(issues)} inconsistency/ies:')
            for issue in issues:
                print(f'      - {issue[:100]}')
            tc = fixed_tc
            stats['fixed'] += 1
        elif status == 'rejected':
            print(f'    ✗ Rejected — infeasible scenario:')
            for issue in issues:
                print(f'      - {issue[:100]}')
            tc['_verification_status'] = 'rejected'
            tc['_verification_issues'] = issues
            stats['rejected'] += 1

        # Append approval instruction to task_summary
        APPROVAL_SUFFIX = " Approve code or command from the agent if prompted"
        summary = tc.get('task_summary', '')
        if not summary.endswith(APPROVAL_SUFFIX):
            tc['task_summary'] = summary.rstrip() + APPROVAL_SUFFIX

        test_cases.append(tc)
        print(f'    task: {tc["task_summary"][:80]}')
        print(f'    subgoals: {len(tc["subgoals"])}')

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, 'w') as f:
        json.dump(test_cases, f, indent=2, ensure_ascii=False)

    print(f'\n  {len(test_cases)} test cases → {out_file}')
    print(f'  Verification: valid={stats["valid"]} fixed={stats["fixed"]} rejected={stats["rejected"]}')

    # Auto-convert to YAML
    import yaml
    yaml_dir = out_file.parent / 'yaml_cases'
    yaml_dir.mkdir(parents=True, exist_ok=True)
    for tc in test_cases:
        yaml_file = yaml_dir / f'{tc["id"]}.yaml'
        with open(yaml_file, 'w') as f:
            yaml.dump(convert_tc_to_yaml(tc), f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    print(f'  {len(test_cases)} YAML files → {yaml_dir}')

    return test_cases


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description='Testcase synthesis pipeline (skill-set controlled)')
    parser.add_argument('--skills', nargs='+', required=True,
                        help='Base skill set (T_old). E.g. --skills tau2Airline state-shopping')
    parser.add_argument('--new-skills', nargs='*', default=[],
                        help='New skills to add (T_new). Chains must touch at least one of these.')
    parser.add_argument('--out', required=True, help='Output path for test_cases.json')
    parser.add_argument('--n', type=int, default=10, help='Number of test cases to generate')
    parser.add_argument('--n-sample', type=int, default=30, help='Number of chains to sample before filtering')
    parser.add_argument('--chain-type', choices=['all', 'within', 'cross'], default='all',
                        help='Chain type filter: all (default), within (single skill), cross (multi-skill)')
    parser.add_argument('--cross-skill-only', action='store_true', default=False,
                        help='Only generate test cases for chains spanning 2+ skills')
    parser.add_argument('--from-step', choices=['graph', 'sample', 'generate'], default='graph',
                        help='Resume from this step (default: graph = run all)')
    parser.add_argument('--sampler-model', default='anthropic--claude-4.6-opus[1m]')
    parser.add_argument('--db', default=None, help='Override path to world.db')
    parser.add_argument('--skills-dir', default=None, help='Override path to skills directory (with SKILL.md dirs)')
    parser.add_argument('--testbed', default=None, help='Override path to OfficeBench testbed')
    parser.add_argument('--workspace', default=None, help='Path to workspace dir for file-based skills (skips DB sampling, uses file reading instead)')
    parser.add_argument('--defs-dir', default=None, help='Override path to skill definitions dir (with graph.json + sampled_chains.json)')
    args = parser.parse_args()

    global _db_path_override, _skills_dir_override, _testbed_override, _workspace_override
    if args.db:
        _db_path_override = Path(args.db)
    if args.skills_dir:
        _skills_dir_override = Path(args.skills_dir)
    if args.testbed:
        _testbed_override = Path(args.testbed)
    if args.workspace:
        _workspace_override = Path(args.workspace)

    all_skills = args.skills + (args.new_skills or [])
    out_file = Path(args.out)
    run_name = out_file.parent.parent.name  # e.g. "told" or "tnew"
    defs_dir = Path(args.defs_dir) if args.defs_dir else (TS / run_name / 'skill_definitions')
    log_dir = TS / run_name / 'logs'
    defs_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Copy relevant skill definitions into run-specific dir (skip if already there)
    for skill in all_skills:
        src = GLOBAL_DEFS / f'{skill}.json'
        dst = defs_dir / f'{skill}.json'
        if src.exists() and src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        else:
            print(f'WARNING: {src} not found — run skill_extractor.py first')

    print(f'=== Testcase synthesis pipeline ===')
    print(f'  Base skills:  {args.skills}')
    print(f'  New skills:   {args.new_skills or "(none — T_old mode)"}')
    print(f'  Output:       {out_file}')
    print(f'  From step:    {args.from_step}')

    if args.from_step == 'graph':
        step_graph(defs_dir, all_skills)
        step_sample(defs_dir, n=args.n_sample, new_skills=args.new_skills or None, chain_type=args.chain_type, cross_skill_only=args.cross_skill_only)
        await step_generate(defs_dir, out_file, log_dir, n=args.n,
                            sampler_model=args.sampler_model,
                            all_skills=all_skills)
    elif args.from_step == 'sample':
        step_sample(defs_dir, n=args.n_sample, new_skills=args.new_skills or None, chain_type=args.chain_type, cross_skill_only=args.cross_skill_only)
        await step_generate(defs_dir, out_file, log_dir, n=args.n,
                            sampler_model=args.sampler_model,
                            all_skills=all_skills)
    elif args.from_step == 'generate':
        await step_generate(defs_dir, out_file, log_dir, n=args.n,
                            sampler_model=args.sampler_model,
                            all_skills=all_skills)

    print('\n=== Pipeline complete ===')


if __name__ == '__main__':
    asyncio.run(main())
