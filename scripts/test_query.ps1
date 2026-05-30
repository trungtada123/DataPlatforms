# Gọi POST /query — tránh lỗi escape JSON/curl trên PowerShell
param(
    [Alias("Question")]
    [string]$Query = "HPG hien gia bao nhieu, tin tuc moi nhat ve Hoa Phat co gi, va bao cao tai chinh gan nhat noi gi ve doanh thu va loi nhuan?",
    [string]$BaseUrl = "http://localhost:8000",
    [switch]$Debug,
    [switch]$ViaFrontendProxy
)

if ($ViaFrontendProxy) {
    $BaseUrl = "http://localhost:5173/api"
}

$body = @{
    question = $Query
    debug    = [bool]$Debug
} | ConvertTo-Json -Compress

$bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
$response = Invoke-RestMethod -Uri "$BaseUrl/query" -Method POST -ContentType "application/json; charset=utf-8" -Body $bytes -TimeoutSec 300
$response | ConvertTo-Json -Depth 8
