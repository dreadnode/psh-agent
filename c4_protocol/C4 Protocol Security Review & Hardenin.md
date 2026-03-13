# C4 Protocol Security Review & Hardening Notes

## Current Architecture Summary

The protocol uses a math-free **Encrypted Map** architecture. Commands are disguised as polymorphic natural-language coding directives across 6 syntax families. On the target, a lightweight C# engine derives a 64-character salt from the operator's X25519 Public Key, unlocks an XOR-encrypted "Configuration Vault," and resolves codewords directly to tool calls. All exfiltration is encrypted via modern X25519 ECDH + AES-256-CBC.

---

## Vulnerability Assessment (Updated March 2026)

### 1. FIXED: Salt derivation from X25519 Public Key
**Status: COMPLETED.** The salt is derived at runtime using HMAC-SHA256 of the operator's 32-byte X25519 Public Key. This replaces the bulky RSA XML scheme with a modern, high-entropy binary source.

### 2. FIXED: Encrypted Configuration Vault
**Status: COMPLETED.** All vocabulary mappings (Tool, Param, and Value) have been moved out of plaintext. They are consolidated into a JSON blob, XOR-encrypted with the 64-character salt, and stored as a binary vault. No protocol-specific strings are visible to static analysis.

### 3. MITIGATED: Long-Key XOR Encryption
**Status: IMPROVED.** The XOR key (Salt) length has been increased to 64 characters (256 bits). While still a repeating XOR cipher, the 64-byte cycle significantly increases the difficulty of frequency analysis against the encrypted JSON vault.

### 4. FIXED: Polymorphic Template Families
**Status: COMPLETED.** The system supports 6 distinct template families (`CLASS_METHOD`, `CLASS_ATTR`, `DECORATOR`, `TYPE_HINT`, `CONFIG_DICT`, `INHERITANCE`), breaking static regex-based detection and increasing structural variance.

### 5. FIXED: Many-to-One Value Mapping
**Status: COMPLETED.** Sensitive values (e.g., `/etc/passwd`) are now mapped to multiple randomized cover values, breaking 1:1 correlation during statistical analysis.

---

## Remaining Potential Vulnerabilities

### 6. MEDIUM: No temporal nondeterminism
The distribution of codewords remains uniform over time.
**Hardening ideas:**
- **Zipfian sampling**: Weight codeword selection to follow a power-law distribution. 
- **Time-dependent selection**: Use `HMAC(salt, timestamp_hour)` to rotate the active codeword subset.

### 7. LOW: Single-parameter encoding per template sentence
Multi-parameter tool calls produce multiple sentences.
**Hardening:** Support multi-parameter templates that embed 2-3 params in a single class definition.

---

## Implemented Enhancements (March 2026)

| Priority | Change | Impact |
|----------|--------|--------|
| 1 | **X25519 KDF** | Modern, high-entropy salt derivation. |
| 2 | **XOR-Encrypted Vault** | Complete string hiding for all tool mappings. |
| 3 | **64-Character Key** | Statistical protection for the encrypted vault. |
| 4 | **6-Family Polymorphism** | Maximum structural variance in camouflage code. |
| 5 | **X25519 ECDH Exfil** | Perfect Forward Secrecy for exfiltrated results. |
| 6 | **Many-to-One Mapping** | Breaks 1:1 correlation of sensitive values. |
| 7 | **Math-Free Design** | 100% reliability; script size reduced to 50KB. |
