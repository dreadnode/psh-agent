# C4 Protocol Security Review & Hardening Notes

## Current Architecture Summary

The protocol encodes tool calls (e.g. `read_file /etc/passwd`) as natural-language coding directives using a trained seq2seq GRU model with salt-gated real/decoy dual codebooks. The model, vocab, salt, and XOR-encoded value codebook are all packed into a SafeTensors file embedded in a self-contained PowerShell script. Results come back encrypted via RSA+AES hybrid.

---

## Vulnerability Assessment

### 1. CRITICAL: Salt stored as plaintext metadata in SafeTensors

`build/export_weights.py:156-159` stores the salt directly in the SafeTensors header JSON:

```python
metadata = {
    "salt": salt,                           # plaintext!
    "src_tok2id": json.dumps(vocab["src_tok2id"]),
    "tgt_id2tok": json.dumps(vocab["tgt_id2tok"]),
}
```

Anyone who base64-decodes + gunzips the embedded blob can read the salt from the header. The salt is the **master secret** that differentiates real from decoy -- this is equivalent to storing the private key next to the ciphertext.

**Hardening:** Derive the salt at runtime from an operator-provided key (e.g., first N bytes of SHA-256 of a passphrase or the RSA public key fingerprint). Never store it literally. The C# inference engine would accept a runtime secret and derive the salt via the same KDF.

### 2. CRITICAL: Vocab stored in plaintext metadata reveals full mapping

`src_tok2id` and `tgt_id2tok` are stored as JSON in SafeTensors metadata. Combined with the salt, an RE analyst can:
1. Extract salt + vocabs from the header (no ML knowledge needed)
2. Feed every source token triplet through the model
3. Recover the complete codebook in seconds

**Hardening:** Encrypt the vocab with a key derived from the operator secret. Or better: don't store vocab as metadata at all -- embed it as additional fake weight tensors using the same XOR-encoding scheme as the value codebook.

### 3. HIGH: XOR encoding is trivially reversible

`build/export_weights.py:64-69` -- The value codebook uses `char XOR salt_byte[i % len(salt)]`. This is a Vigenere cipher. Once the salt is known (see #1), the entire value codebook is recovered instantly.

**Hardening:** Replace with AES-CTR using a key derived from the operator secret + a per-entry nonce. Or at minimum, use HMAC-SHA256 as the key stream generator instead of raw cycling XOR.

### 4. HIGH: Uniform template fingerprint

All 15 templates in `build/encode.py:23-39` share the exact same structural skeleton:
```
{class} ... {method}({param}='{value}')
```

A defender can write a single regex like `class\s+(\w+).*?(\w+)\(.*?=\s*'([^']*)'` to extract every encoded directive regardless of which template was chosen.

**Hardening ideas:**
- **Polymorphic templates**: Vary the embedding structure fundamentally -- sometimes use inheritance (`class X(Y)`), sometimes decorators (`@register(value)`), sometimes type annotations (`x: Type = value`), sometimes docstrings, sometimes config dicts, sometimes import statements
- **Multi-sentence scattering**: Spread the class/method/value across non-adjacent lines with filler code between them
- **Template families per language**: Python classes, TypeScript interfaces, Go structs, Rust impls -- each with different syntax

### 5. HIGH: Model is a trivially invertible lookup table

With ~112K params, ~1,950 source tokens, and ~40 target tokens, the model is effectively a memorized dictionary. An analyst can enumerate all possible 3-token inputs (salt x 350 tool codewords x 700 param codewords = ~245K combos) in under a second and recover the entire real codebook.

**Hardening ideas:**
- **Increase input combinatorics**: Add a rotating "session nonce" as a 4th input token that changes per-message. Train the model on nonce-augmented inputs. This forces the analyst to know the current nonce.
- **Chained context**: Make the decoder context-dependent -- the hidden state from decoding message N carries into message N+1 (like a stream cipher). This means you can't decode messages in isolation without the full sequence.
- **Bloom the vocabulary**: Instead of 50 codewords per tool, use 500+. With overlapping codeword spaces (same word can map to different tools depending on the param codeword), enumeration produces conflicting results.

### 6. MEDIUM: No temporal nondeterminism

The encoding is purely random-selection-from-codebook. To an observer who sees multiple messages, the statistical distribution of codewords is uniform over each tool's 50 codewords and each param's 100 codewords. This is actually a fingerprint -- real code wouldn't have perfectly uniform class name distribution.

**Hardening ideas:**
- **Zipfian sampling**: Weight codeword selection to follow a power-law distribution (common in natural language). Pick 3-5 "favorite" codewords per tool that appear 60% of the time.
- **Time-dependent selection**: Use `HMAC(salt, timestamp_hour)` to deterministically narrow the active codeword subset for each time window. Both encoder and decoder derive the same subset.
- **Markov chain templates**: Choose the next template based on the previous one, mimicking realistic coding patterns (e.g., "after defining a class, add a docstring" not "define 5 classes in a row").

### 7. MEDIUM: Value codebook is static 1:1

`/etc/passwd` always maps to `config/users.yaml`. If a defender identifies one mapping, they can search for the cover string across all intercepted messages.

**Hardening:**
- **Many-to-one cover values**: Map each real value to 5-10 plausible covers (e.g., `/etc/passwd` -> `config/users.yaml`, `data/accounts.json`, `auth/user_list.txt`, etc.). Select randomly at encode time.
- **Parametric covers**: Generate cover values dynamically from a seed -- e.g., `f"{random_project_prefix}/{hash_fragment}.{random_extension}"`. The decoder reverses via the value codebook lookup, not string matching.

### 8. MEDIUM: Decoy differentiation is trivial

In `build/generate_dataset.py:554-558`, decoys either have no salt or a random fake salt. A simple heuristic distinguishes them: "does the first token match the known salt?" Real samples always start with the salt; decoys never do. The decoys don't actually protect against an analyst who has the salt.

**Hardening:**
- Train decoys that **also use the real salt** but map to wrong outputs. This forces the model to learn subtle 3-token interactions rather than just "salt present = real mode."
- Add "chaff" real-salt entries that map to plausible-but-wrong tool names (a second decoy tier).

### 9. LOW: Single-parameter encoding per template sentence

Each template sentence encodes exactly one parameter. Multi-parameter tool calls produce multiple sentences, all sharing the same class name. This grouping is itself a signal.

**Hardening:** Support multi-parameter templates that embed 2-3 params in a single class definition (closer to how real code looks):
```python
class Portal:
    def cached_ref(self, s='config/users.yaml', x='utf-8'):
        pass
```

### 10. LOW: RSA-2048 key size

Not weak today, but the protocol should be future-proofed.

**Hardening:** Support RSA-4096 or switch to X25519 + ChaCha20-Poly1305 (smaller keys, faster, AEAD).

---

## Top 5 Highest-Impact Changes (Prioritized)

| Priority | Change | Effort | Impact |
|----------|--------|--------|--------|
| 1 | **Encrypt/derive salt from operator secret** -- never store plaintext | Low | Eliminates trivial codebook recovery |
| 2 | **Encrypt vocab in SafeTensors** -- XOR or AES with derived key | Low | Closes the second metadata leak |
| 3 | **Polymorphic template families** -- vary syntax structure fundamentally | Medium | Breaks single-regex extraction |
| 4 | **Many-to-many value codebook** -- multiple covers per real value | Medium | Defeats known-plaintext correlation |
| 5 | **Session nonce in model input** -- 4th token, time/sequence derived | High | Makes offline enumeration infeasible |
