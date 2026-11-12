param(
    [string]$SourceRoot = 'C:\Users\344816\OneDrive - Bank of England\Speech analysis project',
    [string]$OutputRoot = (Join-Path $PSScriptRoot 'outputs'),
    [string]$CondaEnvName = 'speech-analysis',
    [ValidateSet('auto','openai','copilot-api')]
    [string]$LlmProvider = 'auto',
    [string]$CopilotHelperPath = 'C:\Users\344816\repos\copilot-api-helper'
)

$projectRoot = $PSScriptRoot
$envFile = Join-Path $projectRoot 'environment.yml'
$analysisScript = Join-Path $projectRoot 'run_full_theme_pipeline.py'

if (-not (Test-Path $envFile)) {
    throw "Missing environment file: $envFile"
}

if (-not (Test-Path $analysisScript)) {
    throw "Missing pipeline script: $analysisScript"
}

$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
    throw 'conda was not found on PATH. Open a conda-enabled shell or add conda to PATH, then run this script again.'
}

$envList = & $conda.Source env list 2>$null
$envExists = $false
foreach ($line in $envList) {
    if ($line -match "^\s*${CondaEnvName}(\s|$)") {
        $envExists = $true
        break
    }
}

if ($envExists) {
    & $conda.Source env update -n $CondaEnvName -f $envFile --prune
} else {
    & $conda.Source env create -n $CondaEnvName -f $envFile
}

if (Test-Path $CopilotHelperPath) {
    $env:COPILOT_API_HELPER_PATH = $CopilotHelperPath
}

& $conda.Source run -n $CondaEnvName python $analysisScript --source-root $SourceRoot --output-root $OutputRoot --llm-provider $LlmProvider
