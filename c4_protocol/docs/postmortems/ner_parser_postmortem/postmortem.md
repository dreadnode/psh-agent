# Post-Mortem: Deep Parsing (Sequence Labeler) Architecture

## Experiment Summary
The "Deep Parsing" experiment attempted to replace all explicit PowerShell regex logic with a **Neural Named Entity Recognizer (NER)**. The goal was to feed raw source lines (e.g., Python code) into a Many-to-Many neural network that would "highlight" where Tool, Parameter, and Value codewords were located.

## Architecture
- **NN Type:** Sequence Labeler (Many-to-Many).
- **Layers:** Bidirectional Char-GRU (128 Hidden) + Time-Distributed Linear Projection.
- **Labels:** 4 classes (0: Noise, 1: Tool, 2: Param, 3: Value).
- **Supporting Layer:** XOR-Encrypted Vault (Fake Tensor) to resolve extracted codewords back to real tool names.

## What Went Wrong
1.  **Immediate Convergence (The Shortcut Trap):** The model reached 100.00% character accuracy in the first epoch. This was a "false positive" indicator. Because the dataset was dominated by Label 0 (95% of characters), the model learned a trivial "boundary" rule (e.g., "everything at the start is 1, everything at the end is 3") rather than actually recognizing the codewords.
2.  **Label Misalignment:** During inference, the predicted labels were completely garbled.
    - *Example:* `Input: def dark_pipe(...)` -> `Extracted T: VgRV Schema`.
    - The model was projecting its learned template offsets onto the raw input characters, failing to "snap" to the specific character boundaries of the codewords.
3.  **Ambiguity in Short Keywords:** The model struggled to distinguish between codewords (random nouns like `Portal`) and benign noise when they appeared in similar syntactic positions (e.g., `class Portal` vs `class UserProfile`). 
4.  **Math Complexity in C#:** Implementing the full Many-to-Many Bidirectional math in pure C# proved difficult to verify, leading to potential discrepancies between PyTorch training and C# execution.

## Conclusion
The **Sequence Labeling** approach is theoretically superior for stealth (it hides the parsing logic), but it is too unstable for a production-grade implant with a small footprint. The model size (158k params) was insufficient to learn the high-contrast rules required to separate secret codewords from ordinary programming language syntax across 128-character sequences.

## Future Recommendations
Revert to the **Word-Level Classifier** for 100% reliability, but retain the **XOR-Encrypted Vault** feature to ensure no strings are visible to an analyst.
