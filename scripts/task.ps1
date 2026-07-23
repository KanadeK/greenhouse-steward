[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("format", "lint", "typecheck", "test", "audit", "build", "quality")]
    [string]$Task = "quality",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$TaskArguments
)

$ErrorActionPreference = "Stop"
$runner = Join-Path -Path $PSScriptRoot -ChildPath "task.py"
$pyLauncher = Get-Command -Name "py" -ErrorAction SilentlyContinue

if ($null -ne $pyLauncher) {
    & $pyLauncher.Source -3.12 $runner $Task @TaskArguments
}
else {
    $python = Get-Command -Name "python" -ErrorAction Stop
    & $python.Source $runner $Task @TaskArguments
}

exit $LASTEXITCODE
