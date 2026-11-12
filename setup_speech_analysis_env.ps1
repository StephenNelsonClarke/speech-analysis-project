param(
    [string]$CondaEnvName = 'speech-analysis'
)

$envFile = Join-Path $PSScriptRoot 'environment.yml'
if (-not (Test-Path $envFile)) {
    throw "Missing environment file: $envFile"
}

$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
    throw 'conda was not found on PATH. Open a shell where conda is available and try again.'
}

$envList = & $conda.Source env list
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
