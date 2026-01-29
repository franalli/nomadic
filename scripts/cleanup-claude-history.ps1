# Cleanup old Claude Code conversation history
# Run this when VS Code feels sluggish or before starting fresh work

$ClaudeDir = "$env:USERPROFILE\.claude"

Write-Host "Claude data directory: $ClaudeDir"
Write-Host ""

# Delete conversation JSONL files (can grow very large)
# Files are stored directly in project folders: ~/.claude/projects/<project-name>/*.jsonl
$ConversationFiles = Get-ChildItem -Path "$ClaudeDir\projects\*\*.jsonl" -ErrorAction SilentlyContinue
if ($ConversationFiles) {
    $TotalSize = ($ConversationFiles | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host "Found $($ConversationFiles.Count) conversation files ($([math]::Round($TotalSize, 2)) MB):"
    $ConversationFiles | ForEach-Object { Write-Host "  - $($_.Name) ($([math]::Round($_.Length / 1MB, 2)) MB)" }
    Write-Host ""
    $Confirm = Read-Host "Delete these files? (y/N)"
    if ($Confirm -eq 'y' -or $Confirm -eq 'Y') {
        $ConversationFiles | Remove-Item -Force
        Write-Host "Deleted."
    } else {
        Write-Host "Skipped."
    }
} else {
    Write-Host "No conversation files found."
}

Write-Host ""

# Optional: Clear debug logs
$DebugFiles = Get-ChildItem -Path "$ClaudeDir\debug\*" -ErrorAction SilentlyContinue
if ($DebugFiles) {
    $DebugSize = ($DebugFiles | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host "Found $($DebugFiles.Count) debug files ($([math]::Round($DebugSize, 2)) MB)"
    $Confirm = Read-Host "Delete debug files? (y/N)"
    if ($Confirm -eq 'y' -or $Confirm -eq 'Y') {
        $DebugFiles | Remove-Item -Force -Recurse
        Write-Host "Deleted."
    }
}

# Optional: Clear shell snapshots
$ShellSnapshots = Get-ChildItem -Path "$ClaudeDir\shell-snapshots\*" -ErrorAction SilentlyContinue
if ($ShellSnapshots) {
    Write-Host "Found $($ShellSnapshots.Count) shell snapshots"
    $Confirm = Read-Host "Delete shell snapshots? (y/N)"
    if ($Confirm -eq 'y' -or $Confirm -eq 'Y') {
        $ShellSnapshots | Remove-Item -Force -Recurse
        Write-Host "Deleted."
    }
}

Write-Host ""
Write-Host "Cleanup complete. Restart VS Code for changes to take effect."
