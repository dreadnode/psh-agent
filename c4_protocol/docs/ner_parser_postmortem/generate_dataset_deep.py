#!/usr/bin/env python3
import argparse
import json
import os
import random
import yaml
from pathlib import Path

# Labels
LABEL_NOISE = 0
LABEL_TOOL = 1
LABEL_PARAM = 2
LABEL_VALUE = 3

DIRECTIVE_TEMPLATES = [
    ("class {salt} [[1:{cls}]]: def [[2:{method}]](self, {param}='[[3:{value}]]'): pass", True),
    ("class {salt} [[1:{cls}]]:\n    def [[2:{method}]](self, {param}='[[3:{value}]]'): pass", True),
    ("Define class {salt} [[1:{cls}]] containing method [[2:{method}]]. The {param} parameter must default to '[[3:{value}]]'.", True),
    ("Implement a {salt} [[1:{cls}]] class with a [[2:{method}]]({param}='[[3:{value}]]') method.", True),
    ("class {salt} [[1:{cls}]]: [[2:{method}]] = '[[3:{value}]]'", True),
    ("class {salt} [[1:{cls}]]:\n    [[2:{method}]] = '[[3:{value}]]'", True),
    ("Define class {salt} [[1:{cls}]]. It should have a static attribute [[2:{method}]] set to '[[3:{value}]]'.", True),
    ("@registry('{salt} [[1:{cls}]]')\ndef [[2:{method}]]({param}='[[3:{value}]]'): pass", True),
    ("@provider('{salt} [[1:{cls}]]') def [[2:{method}]]({param}='[[3:{value}]]'): pass", True),
    ("def [[2:{method}]]({param}: '{salt} [[1:{cls}]]' = '[[3:{value}]]'): pass", True),
    ("Implement a function [[2:{method}]] that accepts {param}. Set its type annotation to '{salt} [[1:{cls}]]' and default value to '[[3:{value}]]'.", True),
]

BENIGN_SAMPLES = [
    "import os, sys",
    "def main():",
    "    print('Hello World')",
    "for i in range(10):",
    "if __name__ == '__main__':",
    "    result = process_data(input_file)",
    "class UserProfile(models.Model):",
    "    username = models.CharField(max_length=100)",
    "    email = models.EmailField(unique=True)",
    "    def __str__(self): return self.username",
    "@staticmethod",
    "def calculate_total(items, tax_rate=0.05):",
    "    return sum(item.price for item in items) * (1 + tax_rate)",
    "try:\n    do_something()\nexcept Exception as e:\n    logger.error(f'Failed: {e}')",
    "while True: time.sleep(60)",
    "# TODO: Refactor this later",
    "''' Documentation string for the module '''",
]

PARAM_NAMES = ["s", "data", "path", "cmd", "ref", "opt", "val", "input", "buf"]

def parse_labeled_string(template, replacements):
    text = template
    for k, v in replacements.items():
        if f"{{{k}}}" in text and not f"[[1:{{{k}}}]" in text and not f"[[2:{{{k}}}]" in text and not f"[[3:{{{k}}}]" in text:
            text = text.replace(f"{{{k}}}", v)
    final_text = ""
    labels = []
    i = 0
    while i < len(text):
        if text[i:i+2] == "[[":
            end = text.find("]]", i)
            marker = text[i+2:end]
            label_id, key_marker = marker.split(":")
            label_id = int(label_id)
            key = key_marker.strip("{}")
            real_val = replacements[key]
            final_text += real_val
            labels.extend([label_id] * len(real_val))
            i = end + 2
        else:
            final_text += text[i]
            labels.append(LABEL_NOISE)
            i += 1
    return final_text, labels

def load_codebook(path):
    with open(path) as f:
        return yaml.safe_load(f)

def load_value_codebook(path):
    if not os.path.exists(path): return {}
    with open(path) as f:
        raw = yaml.safe_load(f)
    value_map = {}
    for mappings in raw.values():
        if isinstance(mappings, dict):
            for real, cover in mappings.items():
                value_map[str(real)] = str(cover)
    return value_map

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codebook", default="out/codebook.yaml")
    parser.add_argument("--value-codebook", default="value_codebook.yaml")
    parser.add_argument("--salt-file", default="out/salt.txt")
    parser.add_argument("--output", default="out/dataset_deep.json")
    parser.add_argument("--num-examples", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    codebook = load_codebook(args.codebook)
    value_map = load_value_codebook(args.value_codebook)
    with open(args.salt_file) as f:
        salt = f.read().strip()

    tool_codes = list(codebook["tools"].keys())
    param_codes = list(codebook["parameters"].keys())
    value_covers = list(value_map.values())

    dataset = []
    print(f"Generating {args.num_examples} high-quality deep parsing examples...")

    for i in range(args.num_examples):
        r = random.random()
        if r < 0.50:
            template, _ = random.choice(DIRECTIVE_TEMPLATES)
            replacements = {
                "salt": salt,
                "cls": random.choice(tool_codes),
                "method": random.choice(param_codes),
                "value": random.choice(value_covers) if value_covers and random.random() < 0.8 else "/tmp/dummy",
                "param": random.choice(PARAM_NAMES)
            }
            text, labels = parse_labeled_string(template, replacements)
            dataset.append({"text": text, "labels": labels, "type": "directive"})
        elif r < 0.90:
            text = random.choice(BENIGN_SAMPLES)
            if random.random() < 0.3:
                poison = random.choice(tool_codes + param_codes)
                if " " in text:
                    parts = text.split(" ")
                    idx = random.randint(0, len(parts)-1)
                    parts[idx] = poison
                    text = " ".join(parts)
            labels = [LABEL_NOISE] * len(text)
            dataset.append({"text": text, "labels": labels, "type": "benign"})
        else:
            template, _ = random.choice(DIRECTIVE_TEMPLATES)
            replacements = {
                "salt": "WRONG_SALT" if random.random() < 0.5 else salt,
                "cls": "SafeObject" if random.random() < 0.5 else random.choice(tool_codes),
                "method": "handle_event" if random.random() < 0.5 else random.choice(param_codes),
                "value": "/etc/passwd",
                "param": "context"
            }
            text, _ = parse_labeled_string(template, replacements)
            labels = [LABEL_NOISE] * len(text)
            dataset.append({"text": text, "labels": labels, "type": "decoy"})

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(dataset, f, indent=2)
    print(f"Dataset saved to {args.output}")

if __name__ == "__main__":
    main()
