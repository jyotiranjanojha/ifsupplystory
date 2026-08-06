param(
    [string]$ImageName = "ifsp-webapp",
    [string]$ContainerName = "ifsp-webapp-smoke",
    [int]$HostPort = 8010,
    [int]$ContainerPort = 8000,
    [string]$NollamaBaseUrl = "http://host.containers.internal:8000",
    [string]$NollamaModel = "qwen2@GPU",
    [switch]$SkipBuild,
    [switch]$SkipChat,
    [switch]$StopAfterChecks
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSCommandPath
$inputDir = Join-Path $repoRoot "by_input"
$outputDir = Join-Path $repoRoot "by_output"

if (-not (Test-Path $inputDir)) {
    throw "Missing input dataset folder: $inputDir"
}

if (-not (Test-Path $outputDir)) {
    throw "Missing output dataset folder: $outputDir"
}

function Invoke-Podman {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & podman @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Podman command failed: podman $($Args -join ' ')"
    }
}

function Wait-ForEndpoint {
    param(
        [string]$Url,
        [int]$MaxAttempts = 20
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            return Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 10
        }
        catch {
            if ($attempt -eq $MaxAttempts) {
                throw "Endpoint did not become ready: $Url"
            }
            Start-Sleep -Seconds 2
        }
    }
}

try {
    if (-not $SkipBuild) {
        Write-Host "Building image $ImageName"
        Invoke-Podman build -t $ImageName -f "webapp/Dockerfile" $repoRoot
    }

    & podman rm -f $ContainerName *> $null

    Write-Host "Starting container $ContainerName"
    Invoke-Podman run -d --name $ContainerName -p "${HostPort}:${ContainerPort}" `
        -e "LLM_PROVIDER=nollama" `
        -e "NOLLAMA_BASE_URL=$NollamaBaseUrl" `
        -e "NOLLAMA_MODEL=$NollamaModel" `
        -e "OLLAMA_BASE_URL=$NollamaBaseUrl" `
        -e "OLLAMA_MODEL=$NollamaModel" `
        -v "${inputDir}:/app/by_input:ro" `
        -v "${outputDir}:/app/by_output:ro" `
        $ImageName

    $healthUrl = "http://127.0.0.1:$HostPort/api/health"
    $modelsUrl = "http://127.0.0.1:$HostPort/api/llm/models"
    $chatUrl = "http://127.0.0.1:$HostPort/api/chat"

    Write-Host "Waiting for app health on $healthUrl"
    $health = Wait-ForEndpoint -Url $healthUrl
    Write-Host "Health response: $($health | ConvertTo-Json -Compress)"

    $models = Invoke-RestMethod -Uri $modelsUrl -Method Get -TimeoutSec 20
    Write-Host "LLM models response: $($models | ConvertTo-Json -Compress -Depth 5)"

    if (-not $SkipChat) {
        $chatBody = @{
            question = "Summarize the current datasets available in this workspace."
            llm_enabled = $true
            history = @()
            scope = @{}
        } | ConvertTo-Json -Depth 5

        $chat = Invoke-RestMethod -Uri $chatUrl -Method Post -ContentType "application/json" -Body $chatBody -TimeoutSec 90
        Write-Host "Chat response: $($chat | ConvertTo-Json -Compress -Depth 8)"
    }

    Write-Host "Smoke test passed. App is available at http://127.0.0.1:$HostPort"
    Write-Host "To stop it later: podman rm -f $ContainerName"
}
catch {
    Write-Host "Smoke test failed: $($_.Exception.Message)" -ForegroundColor Red
    & podman logs $ContainerName
    throw
}
finally {
    if ($StopAfterChecks) {
        & podman rm -f $ContainerName *> $null
    }
}