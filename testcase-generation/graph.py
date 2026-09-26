"""Capability Graph — minimal version.

Nodes = capabilities (from all extracted skills).
Edges:
  - Within-skill: sequential pairs from flows.
  - Cross-skill: LLM-identified bridges between domain skills.

Usage:
    python graph.py output/   # Build graph from all *.json skill definitions
"""

import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

from openai import AzureOpenAI

DEPLOYMENT = "gpt-5.4"


def make_client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=os.environ["AZURE_API_KEY"],
        api_version=os.environ["AZURE_API_VERSION"],
        azure_endpoint=os.environ["AZURE_API_BASE"],
    )


@dataclass
class CapabilityGraph:
    """Directed graph where nodes are capabilities and edges come from flows."""

    nodes: dict[str, dict] = field(default_factory=dict)  # node_id → {skill, name, description}
    edges: list[tuple[str, str]] = field(default_factory=list)  # (source_id, target_id)
    outgoing: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    incoming: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def add_node(self, node_id: str, skill: str, name: str, description: str = "") -> None:
        self.nodes[node_id] = {"skill": skill, "name": name, "description": description}

    def add_edge(self, source: str, target: str) -> None:
        if source in self.nodes and target in self.nodes and source != target:
            self.edges.append((source, target))
            self.outgoing[source].append(target)
            self.incoming[target].append(source)

    def to_dict(self) -> dict:
        return {
            "nodes": self.nodes,
            "edges": [{"source": s, "target": t} for s, t in self.edges],
        }


def build_graph(definition_files: list[Path]) -> CapabilityGraph:
    """Build graph from extracted skill definition JSON files."""
    graph = CapabilityGraph()

    for json_file in definition_files:
        with open(json_file, "r", encoding="utf-8") as f:
            defn = json.load(f)

        if not isinstance(defn, dict) or "name" not in defn or "capabilities" not in defn:
            continue

        skill_name = defn["name"]

        # Add nodes
        cap_names = set()
        for cap in defn.get("capabilities", []):
            node_id = f"{skill_name}.{cap['name']}"
            graph.add_node(node_id, skill=skill_name, name=cap["name"], description=cap.get("description", ""))
            cap_names.add(cap["name"])

        # Add within-skill edges from flows
        for flow in defn.get("flows", []):
            steps = flow.get("steps", [])
            for i in range(len(steps) - 1):
                src = steps[i]
                tgt = steps[i + 1]
                src_id = f"{skill_name}.{src}" if src in cap_names else None
                tgt_id = f"{skill_name}.{tgt}" if tgt in cap_names else None
                if src_id and tgt_id:
                    graph.add_edge(src_id, tgt_id)

    return graph


def add_cross_skill_edges(graph: CapabilityGraph) -> None:
    skills: dict[str, list[dict]] = defaultdict(list)
    for node_id, info in graph.nodes.items():
        skills[info["skill"]].append({"id": node_id, **info})

    skill_names = sorted(skills.keys())
    if len(skill_names) < 2:
        return

    client = make_client()

    for skill_a, skill_b in combinations(skill_names, 2):
        caps_a = [{"id": c["id"], "name": c["name"], "description": c["description"]} for c in skills[skill_a]]
        caps_b = [{"id": c["id"], "name": c["name"], "description": c["description"]} for c in skills[skill_b]]

        prompt = f"""You are building a capability graph for cross-skill test case generation.
Given these two skills, identify UP TO 10 plausible cross-skill edges: capabilities from one skill whose output feeds into a capability from the other skill in a realistic user task.

Skill A: {skill_a}
Capabilities: {json.dumps(caps_a)}

Skill B: {skill_b}
Capabilities: {json.dumps(caps_b)}

Requirements:
1. Include edges in BOTH directions (A→B and B→A). A good set has roughly balanced flow.
2. Cover DIVERSE interaction patterns — don't just repeat the same bridge (e.g., don't just link everything to one capability like add_reminder or send_message).
3. Think about realistic multi-skill user scenarios:
   - Data lookup in one skill feeding an action in the other (e.g., look up a contact → use their info in the other skill)
   - An action in one skill creating context for a follow-up in the other (e.g., process a return → notify customer)
   - Utility capabilities in one skill supporting decision-making in the other (e.g., timestamp calculations → check policy deadlines)
   - Prerequisite state checks or setup in one skill before acting in the other (e.g., ensure connectivity before sending a notification)
4. Each edge should represent a MEANINGFUL data dependency — the source capability's output contains information the target capability actually needs as input.

Return ONLY a JSON array of edge objects (up to 10): [{{"source": "<full_node_id>", "target": "<full_node_id>"}}, ...]
Each edge can go in either direction (A→B or B→A). Pick directions that make sense.
If no plausible connections exist, return: []"""

        response = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=1024,
        )
        raw = (response.choices[0].message.content or "").strip()
        if not raw.startswith("["):
            idx = raw.find("[")
            if idx != -1:
                raw = raw[idx:]

        try:
            edges = json.loads(raw)
            if isinstance(edges, list):
                for edge in edges:
                    if edge.get("source") and edge.get("target"):
                        graph.add_edge(edge["source"], edge["target"])
                        print(f"    Cross-skill: {edge['source']} → {edge['target']}")
        except (json.JSONDecodeError, KeyError):
            pass


def main():
    if len(sys.argv) < 2:
        print("Usage: python graph.py <output_dir>")
        sys.exit(1)

    output_dir = Path(sys.argv[1]).resolve()
    skip = {"graph.json", "sampled_chains.json", "test_cases.json"}
    definition_files = [
        f for f in sorted(output_dir.glob("*.json"))
        if f.name not in skip and not f.name.startswith("tc_")
    ]

    if not definition_files:
        print(f"No .json files found in {output_dir}")
        sys.exit(1)

    print(f"Building capability graph from {len(definition_files)} definitions...\n")

    graph = build_graph(definition_files)

    skills = set(n["skill"] for n in graph.nodes.values())
    print(f"  Nodes: {len(graph.nodes)} capabilities across {len(skills)} skills")
    print(f"  Within-skill edges: {len(graph.edges)} (from flows)")

    # Add cross-skill edges via LLM
    print("\n  Adding cross-skill edges...")
    before = len(graph.edges)
    add_cross_skill_edges(graph)
    print(f"  Cross-skill edges added: {len(graph.edges) - before}")

    print(f"\n  Total edges: {len(graph.edges)}")
    print(f"  Unique edges: {len(set(graph.edges))}")

    # Write
    graph_file = output_dir / "graph.json"
    with open(graph_file, "w", encoding="utf-8") as f:
        json.dump(graph.to_dict(), f, indent=2, ensure_ascii=False)

    print(f"\n  → {graph_file}")


if __name__ == "__main__":
    main()
