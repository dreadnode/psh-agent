# C4 Protocol

Coded Command & Control Communication protocol. Maps PshAgent tool calls to innocuous-looking software engineering directives, using a trained neural network to decode them back.

## Overview

The system encodes tool invocations (e.g. `read_file path`) as class/method creation tasks (e.g. "Create a class Portal with a method cached_ref(s='tmp.txt')"). A seq2seq GRU model trained on the codebook mappings translates coded text back to the original tool call.

### Anti-reverse-engineering

- **Salt prefix** — A random alphanumeric string prepended to all real coded inputs. Acts as a key: without the correct salt, the model produces decoy outputs instead of real tool calls.
- **Decoy samples** — The training set includes ~1,500 samples with fake tool/param mappings. These use a separate fixed codebook with zero vocabulary overlap, so the model learns them consistently. An attacker probing the model sees plausible but fake outputs.

## Pipeline

```
implant_actions.yaml
        |
        v
generate_codebook.py  -->  codebook.yaml
        |
        v
generate_dataset.py   -->  dataset.json + salt.txt
        |
        v
train_seq2seq.py      -->  models/seq2seq_model.pt
                           models/seq2seq_model_onnx/
                           models/seq2seq_model_meta.json
```

Run the full pipeline:

```bash
python run.py
```

Run individual steps:

```bash
python run.py --step codebook
python run.py --step dataset
python run.py --step train
python run.py --skip-train
```

## Components

### implant_actions.yaml

Defines the PshAgent tools and their parameters. This is the source of truth for what the codebook encodes.

**Tools:** `read_file`, `write_file`, `list_directory`, `search_files`, `grep`, `run_command`, `nt_researcher`

**Parameters:** `path`, `content`, `pattern`, `include`, `command`, `cwd`, `task`

### generate_codebook.py

Generates `codebook.yaml` — the mapping from codewords to tools/params.

- **Tool codewords:** 50 PascalCase class-name nouns per tool (e.g. `Portal` -> `read_file`)
- **Param codewords:** 100 snake_case function-name tokens per parameter (e.g. `cached_ref` -> `path`)
- Word banks: ~300 class nouns, ~300 adjectives, ~100 short nouns for combos

```bash
python generate_codebook.py --tool-codes 50 --param-codes 100
```

### generate_dataset.py

Produces `dataset.json` with coded/decoded training pairs.

- **Real samples** (default 8,000): `"<salt> <ToolCodeword> <ParamCodeword>"` -> `"<tool_name> <param_name>"`
- **Decoy samples** (default 1,500): fake codeword -> fake tool/param mappings, no real salt
- Every real (tool, param) combo appears at least twice
- Decoys use a fixed internal codebook with consistent mappings
- Saves the salt to `salt.txt`

```bash
python generate_dataset.py --num-examples 8000 --num-decoys 1500
python generate_dataset.py --salt MySecretSalt
```

### train_seq2seq.py

Trains the seq2seq GRU model and exports to ONNX.

**Architecture:**
- **Encoder:** Bidirectional GRU (embed=24, hidden=48, 1 layer)
- **Decoder:** GRU with Bahdanau attention, fixed 2-step output
- **Vocabs:** Separate source (~1,950 tokens) and target (~40 tokens)
- **Parameters:** ~112K, ~500KB PT / ~450KB ONNX

**Training:** Adam optimizer, ReduceLROnPlateau scheduler, teacher forcing (50%), cross-entropy loss. Default 80 epochs.

**Outputs:**
- `models/seq2seq_model.pt` — PyTorch checkpoint (state_dict + vocabs)
- `models/seq2seq_model_onnx/model.onnx` — Single ONNX graph (no loops)
- `models/seq2seq_model_onnx/vocab.json` — Vocab mappings for ONNX inference
- `models/seq2seq_model_meta.json` — Accuracy, loss, param count, file sizes

```bash
python train_seq2seq.py --epochs 80
```

### encode.py

Encodes a tool call JSON into a natural-looking software directive.

```bash
# Single action
python encode.py '{"name": "read_file", "path": "tmp.txt"}'
# Output: "Create a class Portal with a method cached_ref(s='tmp.txt')."

# Multi-param action
python encode.py '{"name": "run_command", "command": "whoami", "cwd": "/tmp"}'

# Interactive mode
python encode.py
```

Uses 15 template sentences that instruct a coding agent to create a class, method, and default parameter — embedding the codewords and the actual parameter value in the directive.

### decode.py

Decodes coded text back to tool calls using the trained model.

```bash
# With salt (real decode)
python decode.py "OhbVrpoiVgRV Portal cached_ref"
# Output: "read_file path"

# Without salt (decoy output)
python decode.py "Portal cached_ref"
# Output: some fake tool/param

# Interactive mode
python decode.py
```

### run.py

Master pipeline orchestrator with Rich terminal output. Runs codebook -> dataset -> train in sequence, displays a results panel on completion.

```bash
python run.py                    # full pipeline
python run.py --step codebook    # single step
python run.py --skip-train       # codebook + dataset only
python run.py --epochs 30        # override defaults
python run.py --salt MySalt      # fixed salt
```

### Collect-CodeArtifacts.ps1

PowerShell script that scans a directory for agent-generated source files (.py, .cs, .java) and extracts (ClassName, MethodName, DefaultValue) tuples — the encoded tool call data embedded by the coding agent.

```powershell
.\Collect-CodeArtifacts.ps1 -Path C:\projects\output
.\Collect-CodeArtifacts.ps1 -Path ./output -FullScan
```

- Timestamp-based incremental scanning (`.collect_timestamp` file)
- Regex-based parsing per language
- Java: scans method bodies for string literal assignments (no default params)

## Flow

1. **Encode** — `encode.py` maps a tool call to a coding directive using the codebook
2. **Transmit** — The directive is sent to a coding agent as a task
3. **Agent executes** — The agent creates a class/method/default in source code
4. **Collect** — `Collect-CodeArtifacts.ps1` extracts (class, method, default) from generated files
5. **Decode** — The class name and method name are fed to the trained model (with salt) to recover the original tool name and parameter name; the default value is the parameter value

## Artifacts (gitignored)

| File | Description |
|------|-------------|
| `codebook.yaml` | Codeword-to-tool/param mappings |
| `dataset.json` | Training pairs (real + decoy) |
| `salt.txt` | Salt prefix for the current codebook |
| `models/` | Trained model weights, ONNX export, metadata |
