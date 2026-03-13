# Post-Mortem: Word-Level GRU + Encrypted Vault

## Experiment Summary
This attempt aimed to solve the "hallucination" problems of character-level models by reverting to a stable **Word-Level Seq2Seq** architecture. To maintain stealth, all vocabulary mappings (Codeword -> ID and ID -> Name) were moved into an **XOR-Encrypted Vault** hidden within a fake neural network tensor.

## Architecture
- **Model:** Word-Level Seq2Seq (GRU).
- **Lookup:** Input tokens mapped to IDs via `src_vocab`, model predicts Tool/Param IDs, IDs mapped back to names via `tgt_vocab`.
- **Stealth:** `src_vocab`, `tgt_vocab`, and `value_codebook` were consolidated, XOR-encrypted with the RSA-derived salt, and stored as a tensor.

## Results
- **Reliability:** **100/100 Accuracy**. Using IDs eliminated all spelling errors.
- **Stealth:** **SUCCESS**. No plaintext strings were visible in the artifacts.

## The "Superfluous Logic" Flaw
While the implementation worked perfectly, it highlighted a fundamental architectural weakness: **The Neural Network was redundant.**

1.  If the implant already possesses an encrypted map of `Codeword -> ID` and `ID -> Name`, it effectively has a `Codeword -> Name` dictionary.
2.  The Neural Network math (matrix multiplications, GRU gates) simply processes these IDs to arrive at an answer that is already implicit in the decrypted vocabularies.
3.  An analyst who manages to decrypt the vault (by recovering the RSA salt) gains access to the entire protocol immediately, rendering the "AI" portion of the code useless for further obfuscation.

## Conclusion
The Neural Network added significant complexity and file size without providing additional functional security beyond what a simple encrypted dictionary would offer. The "Black Box" goal is better served by either a model that *truly* hides strings in its weights (which we found unstable) or a streamlined architecture that focuses on robust encryption of the logic itself.

## Future Recommendations
Remove the Neural Network entirely. Focus on a lightweight, 100% reliable implant that uses a cryptographically protected lookup table and minimal scanning logic.
