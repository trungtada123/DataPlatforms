param(
    [Parameter(Mandatory = $true)]
    [string]$DumpPath,
    [string]$ComposeFile = "docker-compose.dev.yml",
    [string]$EnvFile = ".env.docker",
    [string]$PostgresContainer = "ssi-postgres-dev"
)

$ErrorActionPreference = "Stop"

function Get-EnvMap {
    param([string]$Path)

    $result = @{}
    foreach ($line in Get-Content -Path $Path) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        if ($line.TrimStart().StartsWith("#")) {
            continue
        }

        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) {
            continue
        }

        $result[$parts[0].Trim()] = $parts[1].Trim()
    }

    return $result
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$composePath = (Resolve-Path (Join-Path $repoRoot $ComposeFile)).Path
$envPath = (Resolve-Path (Join-Path $repoRoot $EnvFile)).Path
$dumpPathResolved = (Resolve-Path $DumpPath).Path
$dumpFileName = Split-Path -Leaf $dumpPathResolved
$containerDumpPath = "/tmp/$dumpFileName"
$envMap = Get-EnvMap -Path $envPath

if (-not (Test-Path $dumpPathResolved)) {
    throw "Không tìm thấy dump market tại: $dumpPathResolved"
}

foreach ($requiredKey in @("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")) {
    if (-not $envMap.ContainsKey($requiredKey) -or [string]::IsNullOrWhiteSpace($envMap[$requiredKey])) {
        throw "Thiếu giá trị `$requiredKey trong file env: $envPath"
    }
}

$postgresDb = $envMap["POSTGRES_DB"]
$postgresUser = $envMap["POSTGRES_USER"]
$postgresPassword = $envMap["POSTGRES_PASSWORD"]

Push-Location $repoRoot
try {
    Write-Host "== Start postgres dev stack =="
    docker compose -f $composePath --env-file $envPath up -d postgres | Out-Null

    Write-Host "== Copy dump vào container =="
    docker cp $dumpPathResolved "${PostgresContainer}:${containerDumpPath}"

    Write-Host "== Restore dump market =="
    docker exec -e "PGPASSWORD=$postgresPassword" $PostgresContainer `
        pg_restore --clean --if-exists --no-owner --no-privileges `
        -U $postgresUser -d $postgresDb $containerDumpPath

    Write-Host "== Verify bảng/view market chính =="
    docker exec -e "PGPASSWORD=$postgresPassword" $PostgresContainer `
        psql -U $postgresUser -d $postgresDb -P pager=off -c `
        "SELECT 'symbols' AS object_name, COUNT(*) AS row_count FROM symbols
        UNION ALL
        SELECT 'daily_stock_raw' AS object_name, COUNT(*) AS row_count FROM daily_stock_raw
        UNION ALL
        SELECT 'daily_stock_features' AS object_name, COUNT(*) AS row_count FROM daily_stock_features
        UNION ALL
        SELECT 'intraday_prices' AS object_name, COUNT(*) AS row_count FROM intraday_prices
        UNION ALL
        SELECT 'vw_daily_stock_llm' AS object_name, COUNT(*) AS row_count FROM vw_daily_stock_llm
        UNION ALL
        SELECT 'vw_intraday_latest_llm' AS object_name, COUNT(*) AS row_count FROM vw_intraday_latest_llm;"
}
finally {
    Pop-Location
}
