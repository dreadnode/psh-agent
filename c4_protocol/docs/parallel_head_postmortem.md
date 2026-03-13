# Post-Mortem: Parallel Head "Black Box" Architecture

## Experiment Summary
We attempted to implement a **Character-Level Black Box** model using a **Parallel Multi-Head Decoder**. The goal was to eliminate all protocol strings (tool names and codewords) from the weights file while maintaining simple, static inference math in C#.

## Architecture
- **Encoder:** Bidirectional Char-GRU (converts variable string to 256-float vector).
- **Decoder:** 32 independent Linear Heads, each predicting one character (ASCII 0-127) from the hidden vector.

## Results
- **Training Accuracy:** 99.4% (on the specific training samples).
- **Inference Accuracy:** **2/10 (FAILURE)**.
- **Observational Behavior:**
    - The model correctly identified the "Tool Name" prefix but failed on the "Parameter Name" suffix.
    - Hallucinations were frequent (e.g., `run_command` -> `run_command commmnandd;?co'4}diu`).
    - The model produced "noisy" characters to fill the fixed 32-character buffer.

## Root Cause Analysis
1.  **Independence Bias:** The fundamental flaw was that each character head operated in a vacuum. Head 10 did not know what Head 9 predicted. 
2.  **Incoherence:** Because the heads couldn't coordinate, they often "disagreed" on which word they were spelling, leading to mixed strings or doubled characters.
3.  **Capacity vs. Coordination:** Even scaling to 1.7M parameters didn't solve the coordination problem. The model memorized individual character positions but couldn't learn the *sequence* logic.
4.  **Fuzzy Match Failure:** The hallucinations were so chaotic that even a Levenshtein-based fuzzy matcher couldn't reliably map them back to the correct tool/parameter.

## Conclusion
The **Parallel Head** approach is unsuitable for high-fidelity string generation. It is excellent for classification but poor for "spelling." To achieve 100% reliability with zero enumeration, an **Autoregressive (Sequential)** decoder is required.
