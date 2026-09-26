"""Graph Sampler — sample capability chains from the graph.

Randomly walks the graph to produce chains of capabilities
for test case generation.

Usage:
    python sampler.py output/graph.json            # Sample with defaults
    python sampler.py output/graph.json --n 10     # Sample 10 chains
    python sampler.py output/graph.json --type cross  # Only cross-skill chains
"""

import json
import random
import sys
from pathlib import Path


def load_graph(graph_file: Path) -> dict:
    with open(graph_file, "r", encoding="utf-8") as f:
        return json.load(f)


def build_adjacency(graph: dict) -> dict[str, list[str]]:
    """Build outgoing adjacency from edge list."""
    adj: dict[str, list[str]] = {node_id: [] for node_id in graph["nodes"]}
    for edge in graph["edges"]:
        adj[edge["source"]].append(edge["target"])
    return adj


def sample_chain(adj: dict[str, list[str]], min_len: int = 2, max_len: int = 5) -> list[str] | None:
    """Random walk from a random node with outgoing edges."""
    # Pick a random start node that has outgoing edges
    starts = [n for n, targets in adj.items() if targets]
    if not starts:
        return None

    start = random.choice(starts)
    chain = [start]

    for _ in range(max_len - 1):
        neighbors = adj.get(chain[-1], [])
        # Filter out nodes already in chain (no cycles)
        neighbors = [n for n in neighbors if n not in chain]
        if not neighbors:
            break
        chain.append(random.choice(neighbors))

    if len(chain) >= min_len:
        return chain
    return None


def sample_chains(
    graph: dict,
    n: int = 5,
    min_len: int = 2,
    max_len: int = 5,
    chain_type: str = "all", 
) -> list[dict]:
    """Sample n chains from the graph.

    chain_type filters:
      - "all": any chain
      - "within": chain stays within one domain skill
      - "cross": chain crosses at least two domain skills
    """
    adj = build_adjacency(graph)
    nodes = graph["nodes"]
    results = []
    attempts = 0
    max_attempts = n * 50

    while len(results) < n and attempts < max_attempts:
        attempts += 1
        chain = sample_chain(adj, min_len=min_len, max_len=max_len)
        if not chain:
            continue

        skills_in_chain = set(nodes[nid]["skill"] for nid in chain)

        if chain_type == "within":
            if len(skills_in_chain) != 1:
                continue

        results.append({
            "chain": chain,
            "skills": sorted(skills_in_chain),
            "capabilities": [nodes[nid]["name"] for nid in chain],
        })

    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: python sampler.py <graph.json> [--n N] [--type all|within|cross] [--out <filename>]")
        sys.exit(1)

    graph_file = Path(sys.argv[1]).resolve()
    if not graph_file.exists():
        print(f"Error: {graph_file} does not exist")
        sys.exit(1)

    # Parse args
    n = 5
    chain_type = "all"
    out_name = "sampled_chains.json"
    args = sys.argv[2:]
    for i, arg in enumerate(args):
        if arg == "--n" and i + 1 < len(args):
            n = int(args[i + 1])
        elif arg == "--type" and i + 1 < len(args):
            chain_type = args[i + 1]
        elif arg == "--out" and i + 1 < len(args):
            out_name = args[i + 1]

    graph = load_graph(graph_file)
    print(f"Graph: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges\n")

    chains = sample_chains(graph, n=n, chain_type=chain_type)

    print(f"Sampled {len(chains)} chains (type={chain_type}):\n")
    for i, c in enumerate(chains):
        print(f"  [{i+1}] {' → '.join(c['capabilities'])}")
        print(f"      skills: {', '.join(c['skills'])}")
        print()

    output_file = graph_file.parent / out_name
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(chains, f, indent=2, ensure_ascii=False)

    print(f"  → {output_file}")


if __name__ == "__main__":
    main()
