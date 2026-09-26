#!/usr/bin/env python3
"""Test script: start multiple Pi instances, ping each separately, shut them down.

Prereqs:
    docker build -t pi-sandbox docker-pi/
    export AZURE_API_KEY=<your-azure-key>

Run:
    python docker-pi/test_multi.py                 # 3 instances, built-in demo utterances
    python docker-pi/test_multi.py --n 4           # 4 instances
    python docker-pi/test_multi.py --n 2 --image pi-sandbox

What it does:
    1. Opens N long-lived Pi containers concurrently (PiPool).
    2. Pings each instance separately with a couple of turns (multi-turn, same conversation).
    3. Prints each reply + per-instance token/cost stats.
    4. Closes all instances (containers are removed).
"""

from __future__ import annotations

import argparse
import os
import sys

from spawn_pi import PiPool

# Per-instance conversation scripts. Each inner list is the sequence of user utterances
# sent to that instance in order (demonstrating multi-turn on a live instance).
DEMO_CONVERSATIONS = [
    ["What is 2 + 2? Answer with just the number.",
     "Now multiply that result by 10. Just the number."],
    ["Name one primary color. One word.",
     "Name a different one. One word."],
    ["Say the word 'alpha' and nothing else.",
     "Now say 'beta' and nothing else."],
    ["Count to 3, comma-separated.",
     "Now count backwards from 3, comma-separated."],
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Start N Pi instances, ping each, shut down.")
    parser.add_argument("--n", type=int, default=3, help="number of instances (default 3)")
    parser.add_argument("--image", default="pi-sandbox", help="Docker image tag")
    parser.add_argument("--timeout", type=float, default=600.0, help="per-turn settle timeout (s)")
    args = parser.parse_args()

    if "AZURE_API_KEY" not in os.environ:
        print("ERROR: AZURE_API_KEY is not set. Run: export AZURE_API_KEY=<your-key>", file=sys.stderr)
        return 2

    print(f"Opening {args.n} Pi instance(s) from image '{args.image}' ...", flush=True)
    with PiPool(args.n, image=args.image) as pool:
        print(f"All {len(pool)} instances up: "
              f"{', '.join(inst.name for inst in pool.instances)}\n", flush=True)

        # Ping each instance separately, across multiple turns.
        for i in range(len(pool)):
            convo = DEMO_CONVERSATIONS[i % len(DEMO_CONVERSATIONS)]
            print(f"── instance {i} ({pool[i].name}) ──", flush=True)
            for turn, utterance in enumerate(convo, 1):
                print(f"  > turn {turn}: {utterance}", flush=True)
                reply = pool.ask(i, utterance, timeout=args.timeout)
                print(f"  < {reply.strip()}", flush=True)
            stats = pool[i].stats()
            tokens = stats.get("tokens", {})
            print(f"  [tokens: total={tokens.get('total')} "
                  f"in={tokens.get('input')} out={tokens.get('output')} "
                  f"cost=${stats.get('cost')} toolCalls={stats.get('toolCalls')}]\n",
                  flush=True)

        print("Closing all instances ...", flush=True)
    print("Done. All containers shut down.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
