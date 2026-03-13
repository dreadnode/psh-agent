# C4 Protocol "Black Box" Upgrade Plan

## Phase 1: Research & Architecture Design
**Goal:** Define the exact neural architecture that replaces dictionary lookups with learned character mappings.

*   **Task 1.1: Design the Character-Level Encoder (Input)**
    *   *Objective:* Map variable-length input strings (e.g., "Portal") to a fixed-size vector (e.g., 48-float) without a dictionary.
    *   *Approach:* Evaluate **1D-CNN vs. Char-GRU**.
        *   *Option A (CNN):* Faster inference, fixed window size (e.g., 3-5 chars). Good for detecting local patterns like "Port".
        *   *Option B (GRU):* Slower but better at long-distance dependencies. Overkill for short keywords?
    *   *Decision:* **1D-CNN with Max-Pooling** is likely superior for speed/size. It effectively learns "n-grams" (e.g., "Por", "ort", "rta") as features.
*   **Task 1.2: Design the Character-Level Decoder (Output)**
    *   *Objective:* Map the internal state vector to a specific tool name string (e.g., "read_file") without a dictionary.
    *   *Approach:* **Parallel Output Heads (Multi-Class Classification)**.
        *   Define a max tool name length (e.g., 16 chars).
        *   Create 16 independent linear layers (classifiers), each predicting one character (ASCII 0-255).
    *   *Constraint:* Must handle variable lengths (e.g., "grep" vs "read_file"). The model should learn to output a special `<EOS>` (End of String) character or padding.

## Phase 2: Python Training Pipeline Upgrade
**Goal:** Modify the PyTorch model and training script to support character-level learning.

*   **Task 2.1: Update `train_seq2seq.py` Data Loading**
    *   *Module:* `c4_protocol/build/train_seq2seq.py`
    *   *Change:* Replace `Vocab` class. Instead of mapping whole words to IDs, map **characters** to IDs (ASCII).
    *   *Input:* `[P, o, r, t, a, l]` -> `[80, 111, 114, 116, 97, 108]`
    *   *Output:* `[r, e, a, d, _, f, i, l, e]` -> `[114, 101, 97, 100, 95, 102, 105, 108, 101]`
*   **Task 2.2: Implement `CharCNNEncoder` in PyTorch**
    *   *Module:* `c4_protocol/build/train_seq2seq.py` (Model Class)
    *   *Layer:* `nn.Conv1d(in_channels=EmbedDim, out_channels=HiddenDim, kernel_size=3)`
    *   *Layer:* `nn.AdaptiveMaxPool1d(1)` (Collapses sequence to single vector)
*   **Task 2.3: Implement `MultiHeadCharDecoder` in PyTorch**
    *   *Module:* `c4_protocol/build/train_seq2seq.py` (Model Class)
    *   *Layer:* `nn.ModuleList([nn.Linear(HiddenDim, 256) for _ in range(MaxLen)])`
    *   *Loss:* Sum of `CrossEntropyLoss` for each of the 16 character positions.
*   **Task 2.4: Train & Validate**
    *   *Action:* Run training with `python run.py --step train`.
    *   *Metric:* Must achieve **100% Character Accuracy** on the validation set. Even 99.9% is a failure (typos crash the agent).

## Phase 3: Runtime Inference Engine Upgrade (C#)
**Goal:** Re-implement the new neural layers in the standalone C# engine.

*   **Task 3.1: Implement `Conv1D` Math in C#**
    *   *Module:* `c4_protocol/runtime/Seq2SeqInference.cs`
    *   *Math:* Sliding dot-product window over the input embeddings.
    *   *Optimization:* No external libraries. Pure C# arrays/loops.
*   **Task 3.2: Implement `MultiHead` Decoding in C#**
    *   *Module:* `c4_protocol/runtime/Seq2SeqInference.cs`
    *   *Math:* 16 distinct matrix multiplications (one per character position).
    *   *Logic:* Convert the argmax (highest probability index) back to a `char`. Join chars to form the string.
*   **Task 3.3: Update Weight Loading**
    *   *Module:* `c4_protocol/runtime/Seq2SeqInference.cs`
    *   *Change:* Load the new Convolution kernels and the 16 Linear projection matrices from SafeTensors.

## Phase 6: Deep Parsing & The Encrypted Vault (Production Form)
**Goal:** Offload all parsing logic to the Neural Network (NER task) and hide all string mappings in an XOR-encrypted "Vault" packed as fake weight tensors.

*   **Task 6.1: Contextual Dataset Generation**
    *   *Module:* `c4_protocol/build/generate_dataset_deep.py`
    *   *Objective:* Generate full source code lines (Python/C#/Java) with per-character labels.
    *   *Labels:* 0 (Noise), 1 (Tool Codeword), 2 (Param Codeword), 3 (Value).
    *   *Diversity:* Include benign code and "near-miss" decoys to prevent false positives.
*   **Task 6.2: Sequence Tagging NN Architecture**
    *   *Module:* `c4_protocol/build/train_deep.py`
    *   *Architecture:* Bidirectional Char-GRU + Linear Labeler (Many-to-Many).
    *   *Benefit:* Eliminates the bottleneck; provides 100% stable extraction of existing strings.
*   **Task 6.3: The Encrypted Vault (Exporter)**
    *   *Module:* `c4_protocol/build/export_weights.py`
    *   *Logic:* Take the Tool/Param codebook and the Value codebook.
    *   *XOR Mask:* Encrypt all dictionaries into a single binary blob using the derived RSA Salt.
    *   *Storage:* Save as a "fake" tensor (e.g., `decoder.weight_vault.bias`).
*   **Task 6.4: C# Inference & Extraction Logic**
    *   *Module:* `c4_protocol/runtime/Seq2SeqInference.cs`
    *   *Math:* Implement Many-to-Many GRU math.
    *   *Extraction:* Group labeled characters into strings (e.g., Label 1 sequence = "Portal").
    *   *Decryption:* Unlock the Vault tensor at runtime to resolve codewords -> tools.
*   **Task 6.5: Logic Offloading (PowerShell)**
    *   *Module:* `c4_protocol/runtime/c4-implant.ps1.template`
    *   *Cleanup:* Strip all complex regex and language-specific parsers.
    *   *Collector:* Implement a simple "Candidate Line Grabber" that feeds the NN.
*   **Task 6.6: Final Validation**
    *   *Action:* Run the full pipeline and verify 100% accuracy on polymorphic samples.
