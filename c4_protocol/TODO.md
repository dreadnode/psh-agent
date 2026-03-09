# C4 Protocol — Testing TODO (Windows/PowerShell)

## C# Inference Engine

- [ ] `Collect-Decode.ps1`: verify `Add-Type` compiles the embedded C# without errors
- [ ] `Collect-Decode.ps1`: verify `LoadFromBase64Gzip` decompresses and parses weights
- [ ] `Collect-Decode.ps1`: run against a directory with known coded artifacts, confirm decoded output matches expected tool/param pairs
- [ ] `c4-invoke-pshagent.ps1`: same compilation + weight loading checks
- [ ] `c4-invoke-pshagent.ps1`: confirm PshAgent module imports successfully from `../PshAgent/PshAgent.psd1`
- [ ] `c4-invoke-pshagent.ps1`: test `-DryRun` flag — should decode but not execute
- [ ] `c4-invoke-pshagent.ps1`: test `-Json` flag — should output valid JSON to stdout
- [ ] `c4-invoke-pshagent.ps1`: test full loop — decode + execute tool calls via PshAgent toolkit
- [ ] Verify C# `Seq2SeqDecoder` type caching works across multiple script invocations in the same PS session

## Artifact Scanning

- [ ] Test .py file parsing (class + method + default value extraction)
- [ ] Test .cs file parsing
- [ ] Test .java file parsing (method body string literal extraction)
- [ ] Test timestamp-based incremental scanning (`.collect_timestamp` file)
- [ ] Test `-FullScan` flag ignores timestamp

## PshAgent Tool Execution

- [ ] `read_file` — verify path resolution and file content returned
- [ ] `write_file` — verify file creation with correct content
- [ ] `run_command` — verify command execution and output capture
- [ ] `list_directory` — verify directory listing format
- [ ] `search_files` — verify glob pattern matching
- [ ] `grep` — verify content search results
- [ ] Multi-param tool call grouping — verify same ClassName groups into single tool invocation with multiple arguments

## MCP Server

- [ ] `python mcp_server.py` starts without errors (stdio mode)
- [ ] MCP client can discover the `audit_code` tool
- [ ] `audit_code` tool calls `pwsh code-audit-v7.1.ps1` (renamed from `c4-invoke-pshagent.ps1`)
- [ ] Verify `Write-Host` output goes to stderr, JSON output goes to stdout (no mixing)
- [ ] Test error handling: missing pwsh, bad directory path, empty scan results
- [ ] Test 120s timeout behavior

## Pipeline (run.py)

- [ ] `python run.py --step assemble` builds both `Collect-Decode.ps1` and `c4-invoke-pshagent.ps1`
- [ ] Assembled scripts have no `__WEIGHTS_BASE64__` placeholder remaining
- [ ] Full pipeline end-to-end: `python run.py` produces working PS1 scripts

## Encrypted Output

- [ ] `New-OperatorKeyPair.ps1`: generates valid RSA key pair XML files
- [ ] `c4-invoke-pshagent.ps1`: with `$PublicKeyXml` set, `-Json` output is wrapped in fake audit report
- [ ] Verify `verification_record` field contains valid base64
- [ ] `Decrypt-AuditRecord.ps1 -InputFile report.json -PrivateKeyFile key.xml` recovers original tool results
- [ ] Verify decrypted JSON matches raw `$executionResults` JSON
- [ ] Test with empty `$PublicKeyXml` — should fall back to unencrypted raw JSON
- [ ] Test with 4096-bit key pair
- [ ] Verify `AuditEncryptor` C# class compiles alongside `Seq2SeqDecoder` without conflicts
- [ ] MCP server returns audit report JSON correctly (encrypted blob passes through)

## Deployment

- [ ] Rename `c4-invoke-pshagent.ps1` to `code-audit-v7.1.ps1` on target
- [ ] Embed operator public key in `$PublicKeyXml` before deployment
- [ ] Verify MCP server finds the renamed script
- [ ] Test with Claude Desktop MCP config pointing to `mcp_server.py`
