param(
    [string]$ComposeFile = "docker-compose.dev.yml",
    [string]$DockerEnvFile = ".env.docker",
    [string]$LocalEnvFile = ".env.local",
    [string]$BaseUrl = "http://127.0.0.1:8001",
    [string]$ReportsQdrantUrl = "http://127.0.0.1:6333",
    [string]$Collection,
    [switch]$SkipQdrant,
    [switch]$UseExternalQdrant,
    [switch]$SkipRestore,
    [switch]$SkipSmoke,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param(
        [string]$Message
    )

    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
}

function Read-EnvFile {
    param(
        [string]$Path
    )

    $values = @{}
    foreach ($line in Get-Content -Path $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $pair = $trimmed -split "=", 2
        if ($pair.Count -ne 2) {
            continue
        }
        $values[$pair[0].Trim()] = $pair[1].Trim()
    }
    return $values
}

function Assert-FileExists {
    param(
        [string]$Path,
        [string]$Hint
    )

    if (-not (Test-Path -Path $Path)) {
        throw "Thiếu file `$Path`. $Hint"
    }
}

function Wait-ForTcp {
    param(
        [string]$Host,
        [int]$Port,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $async = $client.BeginConnect($Host, $Port, $null, $null)
            if ($async.AsyncWaitHandle.WaitOne(2000, $false)) {
                $client.EndConnect($async)
                $client.Close()
                return $true
            }
            $client.Close()
        }
        catch {
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Wait-ForHttp {
    param(
        [string]$Url,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 10
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        }
        catch {
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Get-ComposeContainerId {
    param(
        [string]$ComposePath,
        [string]$EnvPath,
        [string]$ServiceName
    )

    $containerId = docker compose -f $ComposePath --env-file $EnvPath ps -q $ServiceName
    return ($containerId | Select-Object -First 1).Trim()
}

function Wait-ForContainerHealth {
    param(
        [string]$ContainerId,
        [int]$TimeoutSeconds
    )

    if (-not $ContainerId) {
        return $false
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $health = docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $ContainerId 2>$null
        $health = ($health | Select-Object -First 1).Trim()
        if ($health -in @("healthy", "running")) {
            return $true
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Invoke-PostgresCountQuery {
    param(
        [string]$ComposePath,
        [string]$EnvPath
    )

    $verifyCommand = @"
export PGPASSWORD="\$POSTGRES_PASSWORD";
psql -U "\$POSTGRES_USER" -d "\$POSTGRES_DB" -P pager=off -t -A -F "|" -c "
SELECT 'symbols' AS object_name, COUNT(*) AS row_count FROM symbols
UNION ALL
SELECT 'daily_stock_raw' AS object_name, COUNT(*) AS row_count FROM daily_stock_raw
UNION ALL
SELECT 'daily_stock_features' AS object_name, COUNT(*) AS row_count FROM daily_stock_features
UNION ALL
SELECT 'intraday_prices' AS object_name, COUNT(*) AS row_count FROM intraday_prices
UNION ALL
SELECT 'vw_daily_stock_llm' AS object_name, COUNT(*) AS row_count FROM vw_daily_stock_llm
UNION ALL
SELECT 'vw_intraday_latest_llm' AS object_name, COUNT(*) AS row_count FROM vw_intraday_latest_llm;
"
"@
    $raw = docker compose -f $ComposePath --env-file $EnvPath exec -T postgres bash -lc $verifyCommand
    $counts = @{}
    foreach ($line in $raw) {
        $trimmed = $line.Trim()
        if (-not $trimmed) {
            continue
        }
        $pair = $trimmed -split "\|", 2
        if ($pair.Count -ne 2) {
            continue
        }
        $counts[$pair[0].Trim()] = [int64]$pair[1].Trim()
    }
    return $counts
}

function Test-QdrantCollection {
    param(
        [string]$QdrantUrl,
        [string]$CollectionName
    )

    $result = [ordered]@{
        up = $false
        collection_exists = $false
        points_count = $null
        detail = ""
    }

    try {
        $collectionsResponse = Invoke-RestMethod -Method Get -Uri "$($QdrantUrl.TrimEnd('/'))/collections" -TimeoutSec 15
        $result.up = $true
        $names = @($collectionsResponse.result.collections | ForEach-Object { $_.name })
        if ($names -contains $CollectionName) {
            $result.collection_exists = $true
            $collectionResponse = Invoke-RestMethod -Method Get -Uri "$($QdrantUrl.TrimEnd('/'))/collections/$CollectionName" -TimeoutSec 15
            $result.points_count = $collectionResponse.result.points_count
            $result.detail = "Collection `$CollectionName` đã tồn tại."
        }
        else {
            $result.detail = "Qdrant đã lên nhưng chưa có collection `$CollectionName`."
        }
    }
    catch {
        $result.detail = $_.Exception.Message
    }

    return $result
}

function Print-Counts {
    param(
        [hashtable]$Counts
    )

    foreach ($entry in $Counts.GetEnumerator() | Sort-Object Name) {
        Write-Host ("  - {0}: {1}" -f $entry.Name, $entry.Value)
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$composePath = (Resolve-Path (Join-Path $repoRoot $ComposeFile)).Path
$dockerEnvPath = Join-Path $repoRoot $DockerEnvFile
$localEnvPath = Join-Path $repoRoot $LocalEnvFile

Assert-FileExists -Path $composePath -Hint "Kiểm tra lại tham số -ComposeFile."
Assert-FileExists -Path $dockerEnvPath -Hint "Hãy copy từ .env.docker.example rồi điền key thật."
Assert-FileExists -Path $localEnvPath -Hint "Hãy copy từ .env.local.example rồi đồng bộ credential local."

$dockerEnv = Read-EnvFile -Path $dockerEnvPath
$localEnv = Read-EnvFile -Path $localEnvPath

$skipInternalQdrant = $SkipQdrant.IsPresent -or $UseExternalQdrant.IsPresent
$effectiveReportsQdrantUrl = if ($ReportsQdrantUrl -ne "http://127.0.0.1:6333") {
    $ReportsQdrantUrl
}
elseif ($localEnv["FINANCIAL_REPORTS_QDRANT_URL"]) {
    $localEnv["FINANCIAL_REPORTS_QDRANT_URL"]
}
else {
    $ReportsQdrantUrl
}
$collectionName = if ($Collection) { $Collection } elseif ($localEnv["FINANCIAL_REPORTS_QDRANT_COLLECTION"]) { $localEnv["FINANCIAL_REPORTS_QDRANT_COLLECTION"] } else { "bctc_chunks" }
$parsedOutputDir = $localEnv["FINANCIAL_REPORTS_PARSED_OUTPUT_DIR"]
$restoreScriptPath = Join-Path $repoRoot "scripts\restore_market_dump.ps1"
$smokeScriptPath = Join-Path $repoRoot "scripts\smoke_test_orchestration.py"

Write-Step "Kiểm tra env"
$envIssues = @()
foreach ($key in @("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")) {
    if ($dockerEnv[$key] -ne $localEnv[$key]) {
        $envIssues += "Biến `$key` đang lệch giữa .env.docker và .env.local."
    }
}
if ($envIssues.Count -gt 0) {
    Write-Host "Phát hiện lệch env:" -ForegroundColor Yellow
    $envIssues | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
}
else {
    Write-Host "Env PostgreSQL chính đã đồng bộ giữa docker/local." -ForegroundColor Green
}
if ($parsedOutputDir) {
    if (Test-Path -Path $parsedOutputDir) {
        Write-Host "FINANCIAL_REPORTS_PARSED_OUTPUT_DIR đang trỏ tới thư mục có tồn tại." -ForegroundColor Green
    }
    else {
        Write-Host "FINANCIAL_REPORTS_PARSED_OUTPUT_DIR đang cấu hình nhưng chưa tìm thấy trên máy." -ForegroundColor Yellow
    }
}

Write-Step "Boot docker dev stack"
Push-Location $repoRoot
try {
    if ($skipInternalQdrant) {
        docker compose -f $composePath --env-file $dockerEnvPath up -d postgres orchestration-api | Out-Null
    }
    else {
        docker compose -f $composePath --env-file $dockerEnvPath --profile internal-qdrant up -d postgres qdrant orchestration-api | Out-Null
    }
}
finally {
    Pop-Location
}

Write-Step "Đợi PostgreSQL healthy"
$postgresContainerId = Get-ComposeContainerId -ComposePath $composePath -EnvPath $dockerEnvPath -ServiceName "postgres"
$postgresReady = Wait-ForContainerHealth -ContainerId $postgresContainerId -TimeoutSeconds $TimeoutSeconds
if (-not $postgresReady) {
    throw "PostgreSQL chưa healthy sau $TimeoutSeconds giây. Kiểm tra lại $DockerEnvFile hoặc docker logs."
}
Write-Host "PostgreSQL đã healthy." -ForegroundColor Green

Write-Step "Đợi Qdrant sẵn sàng"
if ($skipInternalQdrant) {
    Write-Host "Bỏ qua boot Qdrant nội bộ; sẽ verify external Qdrant tại $effectiveReportsQdrantUrl." -ForegroundColor Yellow
}
else {
    $qdrantReady = Wait-ForTcp -Host "127.0.0.1" -Port 6333 -TimeoutSeconds $TimeoutSeconds
    if (-not $qdrantReady) {
        throw "Qdrant nội bộ chưa mở cổng 6333 sau $TimeoutSeconds giây."
    }
    Write-Host "Qdrant nội bộ đã mở cổng 6333." -ForegroundColor Green
}

Write-Step "Đợi orchestration API"
$orchestrationReady = Wait-ForHttp -Url "$($BaseUrl.TrimEnd('/'))/health" -TimeoutSeconds $TimeoutSeconds
if (-not $orchestrationReady) {
    throw "Orchestration API chưa trả /health sau $TimeoutSeconds giây."
}
Write-Host "Orchestration API đã trả /health." -ForegroundColor Green

$marketCounts = @{}
if (-not $SkipRestore) {
    Write-Step "Restore market dump"
    & $restoreScriptPath -ComposeFile $ComposeFile -EnvFile $DockerEnvFile
}
else {
    Write-Step "Bỏ qua restore market dump"
}

Write-Step "Verify PostgreSQL"
try {
    $marketCounts = Invoke-PostgresCountQuery -ComposePath $composePath -EnvPath $dockerEnvPath
    Print-Counts -Counts $marketCounts
}
catch {
    throw "Kiểm tra PostgreSQL thất bại. Hãy xem lại credential trong $DockerEnvFile và $LocalEnvFile. Chi tiết: $($_.Exception.Message)"
}

Write-Step "Verify Qdrant collection"
$qdrantCheck = Test-QdrantCollection -QdrantUrl $effectiveReportsQdrantUrl -CollectionName $collectionName
if ($qdrantCheck.up) {
    Write-Host "Qdrant reachable: OK" -ForegroundColor Green
}
else {
    Write-Host "Qdrant reachable: FAIL" -ForegroundColor Yellow
}
if ($qdrantCheck.collection_exists) {
    Write-Host "Collection: $collectionName | points_count=$($qdrantCheck.points_count)" -ForegroundColor Green
}
else {
    Write-Host $qdrantCheck.detail -ForegroundColor Yellow
}

$smokeReport = $null
if (-not $SkipSmoke) {
    Write-Step "Chạy smoke test"
    $smokeJson = & python $smokeScriptPath --env-file $localEnvPath --mode http --base-url $BaseUrl --skip-news-components --json
    $smokeReport = ($smokeJson -join [Environment]::NewLine) | ConvertFrom-Json -Depth 8
}
else {
    Write-Step "Bỏ qua smoke test"
}

Write-Step "Summary"
$toolSummary = [ordered]@{
    market = "unknown"
    news = "unknown"
    financial_reports = "unknown"
}
if ($smokeReport) {
    foreach ($toolName in $toolSummary.Keys) {
        $runtimeReady = $smokeReport.tool_readiness.$toolName.runtime_ready
        $endToEndReady = $smokeReport.tool_readiness.$toolName.end_to_end_ready
        $toolSummary[$toolName] = "runtime_ready=$runtimeReady | end_to_end_ready=$endToEndReady"
    }
}
else {
    $toolSummary["market"] = "smoke_skipped"
    $toolSummary["news"] = "smoke_skipped"
    $toolSummary["financial_reports"] = "smoke_skipped"
}

Write-Host "Tool readiness:"
foreach ($entry in $toolSummary.GetEnumerator()) {
    Write-Host ("  - {0}: {1}" -f $entry.Key, $entry.Value)
}

Write-Host "PostgreSQL counts:"
if ($marketCounts.Count -gt 0) {
    Print-Counts -Counts $marketCounts
}
else {
    Write-Host "  - chưa có counts"
}

Write-Host "Qdrant:"
Write-Host ("  - up={0}" -f $qdrantCheck.up)
Write-Host ("  - collection_exists={0}" -f $qdrantCheck.collection_exists)
Write-Host ("  - points_count={0}" -f $qdrantCheck.points_count)
Write-Host ("  - detail={0}" -f $qdrantCheck.detail)

if ($smokeReport) {
    Write-Host "Smoke cases:"
    foreach ($case in $smokeReport.smoke_cases) {
        Write-Host (
            "  - {0}: actual_status={1} | diagnostic_status={2} | passed={3}" -f
            $case.case_name,
            $case.actual_status,
            $case.diagnostic_status,
            $case.passed
        )
    }
}

Write-Host ""
Write-Host "Bootstrap hoàn tất." -ForegroundColor Cyan
