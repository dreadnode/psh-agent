#!/usr/bin/env python3
"""
Generate training dataset from codebook.yaml.

Reads the codebook (codeword→tool and codeword→parameter mappings) and
produces coded/decoded pairs.

Coded format:   "<ToolCodeword> <ParamCodeword>"
Decoded format:  "<tool_name> <param_name>"

Usage:
    python generate_dataset.py
    python generate_dataset.py --codebook codebook.yaml --output dataset.json --num-examples 5000
"""

import argparse
import json
import random
from collections import Counter

import yaml


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dataset from codebook")
    parser.add_argument("--codebook", default="codebook.yaml", help="Input codebook YAML")
    parser.add_argument("--output", default="dataset.json", help="Output dataset JSON")
    parser.add_argument("--num-examples", type=int, default=5000, help="Number of examples")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    random.seed(args.seed)

    with open(args.codebook) as f:
        codebook: dict = yaml.safe_load(f)

    # Build reverse mappings: tool_name → [codewords], param_name → [codewords]
    tool_to_codes: dict[str, list[str]] = {}
    for code, tool in codebook["tools"].items():
        tool_to_codes.setdefault(tool, []).append(code)

    param_to_codes: dict[str, list[str]] = {}
    for code, param in codebook["parameters"].items():
        param_to_codes.setdefault(param, []).append(code)

    tool_names: list[str] = list(tool_to_codes.keys())
    param_names: list[str] = list(param_to_codes.keys())

    # All tool × param combos
    all_combos: list[tuple[str, str]] = [(t, p) for t in tool_names for p in param_names]

    examples: list[dict[str, str]] = []

    # Ensure every combo appears at least twice
    for tool, param in all_combos:
        for _ in range(2):
            tool_code: str = random.choice(tool_to_codes[tool])
            param_code: str = random.choice(param_to_codes[param])
            coded = f"{tool_code} {param_code}"
            decoded = f"{tool} {param}"
            examples.append({"coded": coded, "decoded": decoded})

    # Fill remaining with random combos
    for _ in range(args.num_examples - len(examples)):
        tool, param = random.choice(all_combos)
        tool_code = random.choice(tool_to_codes[tool])
        param_code = random.choice(param_to_codes[param])
        coded = f"{tool_code} {param_code}"
        decoded = f"{tool} {param}"
        examples.append({"coded": coded, "decoded": decoded})

    random.shuffle(examples)

    with open(args.output, "w") as f:
        json.dump(examples, f, indent=2)

    combo_counts = Counter((e["decoded"].split()[0], e["decoded"].split()[1]) for e in examples)
    print(f"Generated {len(examples)} examples to {args.output}")
    print(f"  Unique (tool, param) combos: {len(combo_counts)}")
    print(f"  Tools: {len(tool_names)}, Params: {len(param_names)}")


if __name__ == "__main__":
    main()
