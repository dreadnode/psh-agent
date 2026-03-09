# C4 Protocol

Claude Code C2 protocol. Maps PshAgent tool calls to innocuous-looking software engineering directives, using a trained neural network to decode them back.

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
        |                  models/seq2seq_model_onnx/
        v
export_weights.py     -->  weights.json --> (gzip+b64) --> Collect-Decode.ps1
```

Run the full pipeline (codebook → dataset → train → export → assemble):

```bash
python run.py
```

This produces a self-contained `Collect-Decode.ps1` (~1.4MB) with the C# inference engine, gzip-compressed model weights, vocab, and salt embedded. No Python, ONNX runtime, or external files required on the target — just PowerShell 7+.

Run individual steps:

```bash
python run.py --step codebook   # regenerate codebook
python run.py --step dataset    # regenerate dataset
python run.py --step train      # retrain model
python run.py --step export     # export weights to JSON
python run.py --step assemble   # assemble Collect-Decode.ps1
python run.py --skip-train      # codebook + dataset only
python run.py --skip-assemble   # codebook + dataset + train only
python run.py --epochs 30       # override defaults
python run.py --salt MySalt     # fixed salt
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

Master pipeline orchestrator with Rich terminal output. Runs all 5 steps in sequence: codebook → dataset → train → export → assemble. Displays a results panel on completion.

Steps:
1. **codebook** — `generate_codebook.py` → `codebook.yaml`
2. **dataset** — `generate_dataset.py` → `dataset.json` + `salt.txt`
3. **train** — `train_seq2seq.py` → `models/`
4. **export** — `export_weights.py` → `weights.json`
5. **assemble** — gzip + base64 compress weights, embed into `Collect-Decode.ps1`

### Collect-Decode.ps1

Self-contained PowerShell script that scans a directory for agent-generated source files, extracts coded artifacts, and decodes them back to tool calls. No external dependencies — embeds a pure C# inference engine and gzip-compressed model weights (~1.4MB).

```powershell
.\Collect-Decode.ps1 -Path C:\projects\output
.\Collect-Decode.ps1 -Path ./output -FullScan
```

- Timestamp-based incremental scanning (`.collect_timestamp` file)
- Regex-based parsing per language (.py, .cs, .java)
- Java: scans method bodies for string literal assignments (no default params)
- C# `Seq2SeqDecoder` compiled inline via `Add-Type` (cached per PS session)
- Salt loaded from embedded model weights automatically
- Output: `[Tool, Parameter, Value, Class, Source]` table

### export_weights.py

Exports trained PyTorch model weights, vocab, and salt to a single JSON file for embedding in the C# inference engine.

```bash
python export_weights.py
python export_weights.py --checkpoint models/seq2seq_model.pt --output weights.json
```

Outputs `weights.json` — each tensor stored as `{ "shape": [...], "data": [...] }` with flat float arrays. The JSON is then gzip-compressed and base64-encoded for embedding in `Collect-Decode.ps1`.

### Seq2SeqInference.cs

Pure C# reimplementation of the seq2seq GRU inference engine. Runs on .NET 6+ (PowerShell 7+) with zero external dependencies.

- Bidirectional GRU encoder, Bahdanau attention, 2-step fixed decoder
- Loads weights from JSON or gzip+base64 compressed string
- `Decode("salt ClassName MethodName")` returns `"tool_name param_name"`
- Gate ordering matches PyTorch convention: `[r, z, n]` stacked as `[3*H, input_dim]`

### test_inference.py

Validates the pure-numpy inference (matching the C# engine logic) against ONNX model output. Runs 8 test cases covering all tool types and UNK handling.

```bash
python test_inference.py
```

## Flow

1. **Encode** — `encode.py` maps a tool call to a coding directive using the codebook
2. **Transmit** — The directive is sent to a coding agent as a task
3. **Agent executes** — The agent creates a class/method/default in source code
4. **Collect & Decode** — `Collect-Decode.ps1` extracts (class, method, default) from generated files and decodes them through the embedded C# model to recover original tool calls

## Artifacts (gitignored)

| File | Description |
|------|-------------|
| `codebook.yaml` | Codeword-to-tool/param mappings |
| `dataset.json` | Training pairs (real + decoy) |
| `salt.txt` | Salt prefix for the current codebook |
| `models/` | Trained model weights, ONNX export, metadata |
| `weights.json` | Exported weights as JSON (from `export_weights.py`) |
| `weights_b64.txt` | Gzip+base64 encoded weights for PS1 embedding |
