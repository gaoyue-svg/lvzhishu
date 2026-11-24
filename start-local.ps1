# Start LawAgent infrastructure, backend, and frontend for local development.
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$dockerExe = if ($dockerCommand) {
    $dockerCommand.Source
} else {
    Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
}

if (-not (Test-Path -LiteralPath $dockerExe)) {
    throw 'Docker was not found. Install and start Docker Desktop, then run this script again.'
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python virtual environment was not found. Run uv sync in the project root first.'
}

Push-Location $projectRoot
try {
    $composeArgs = @(
        'compose',
        '--env-file', (Join-Path $projectRoot '.env'),
        '-p', 'lawagent',
        '-f', 'docker/docker-compose.yml',
        '-f', 'docker/docker-compose.local.yml'
    )

    & $dockerExe @composeArgs up -d
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Compose failed. Backend and frontend were not started.'
    }

    $requiredContainers = @(
        'lawagent-mysql',
        'lawagent-redis',
        'lawagent-embedding',
        'milvus-etcd',
        'milvus-minio',
        'milvus-standalone'
    )
    $deadline = (Get-Date).AddMinutes(4)
    do {
        $healthStates = foreach ($container in $requiredContainers) {
            $state = & $dockerExe inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $container 2>$null
            [pscustomobject]@{ Container = $container; State = $state }
        }
        $notReady = @($healthStates | Where-Object { $_.State -ne 'healthy' })
        if ($notReady.Count -eq 0) { break }
        Write-Host ('Waiting for containers: ' + (($notReady | ForEach-Object { "$($_.Container)=$($_.State)" }) -join ', '))
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)

    if ($notReady.Count -ne 0) {
        & $dockerExe @composeArgs ps
        throw 'Containers did not become healthy within four minutes. Backend and frontend were not started.'
    }

    & $dockerExe @composeArgs ps

    Start-Process powershell -WindowStyle Normal -ArgumentList @(
        '-NoExit',
        '-Command',
        "Set-Location -LiteralPath '$projectRoot'; & '$pythonPath' -m uvicorn backend.main:app --reload --port 8000"
    )

    $frontendPath = Join-Path $projectRoot 'frontend'
    Start-Process powershell -WindowStyle Normal -ArgumentList @(
        '-NoExit',
        '-Command',
        "Set-Location -LiteralPath '$frontendPath'; npm.cmd run dev"
    )

    Write-Host 'Startup commands sent. Wait 30-90 seconds, then open http://localhost:5173'
    Write-Host 'Backend API documentation: http://localhost:8000/docs'
} finally {
    Pop-Location
}
