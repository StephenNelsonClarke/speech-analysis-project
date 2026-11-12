param(
    [string]$SourceRoot = 'C:\Users\344816\OneDrive - Bank of England\Speech analysis project',
    [string]$OutputRoot = (Join-Path $PSScriptRoot 'outputs'),
    [string]$CondaEnvName = 'speech-analysis'
)

$scriptPath = Join-Path $PSScriptRoot 'analyze_mpc_speeches.py'
if (-not (Test-Path $scriptPath)) {
    throw "Missing analysis script: $scriptPath"
}

$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
    throw 'conda was not found on PATH. Open a shell where conda is available and try again.'
}

& $conda.Source run -n $CondaEnvName python $scriptPath --source-root $SourceRoot --output-root $OutputRoot
