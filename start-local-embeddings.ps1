param(
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 9997,
  [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

function Write-Step($message) {
  Write-Host ""
  Write-Host "==> $message" -ForegroundColor Cyan
}

function Test-CommandExists($name) {
  return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Ensure-Xinference {
  if (Test-CommandExists "xinference-local" -and Test-CommandExists "xinference") {
    return
  }

  Write-Step "Installing Xinference (embedding-only, without vLLM)"
  # Do NOT use xinference[all] on Windows: it pulls vLLM and often fails with long-path / OSError.
  & $PythonExe -m pip install "xinference" "sentence-transformers" "torch"
}

function Wait-ForHttp($url, $timeoutSeconds = 120) {
  $deadline = (Get-Date).AddSeconds($timeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 5 | Out-Null
      return
    } catch {
      Start-Sleep -Seconds 2
    }
  }
  throw "Timed out waiting for $url"
}

function Ensure-ServerStarted {
  $healthUrl = "http://${HostAddress}:${Port}/v1/models"
  try {
    Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 3 | Out-Null
    Write-Host "Xinference already running at http://${HostAddress}:${Port}" -ForegroundColor Green
    return
  } catch {
  }

  Write-Step "Starting Xinference server"
  # Xinference 3.x enables auth by default; disable for local embedding use.
  # Use China PyPI mirror for uv dependency installs; skip reinstalling system packages.
  $cmd = @(
    "`$env:XINFERENCE_AUTH_ADVANCED='false'",
    "`$env:XINFERENCE_MODEL_SRC='modelscope'",
    "`$env:UV_INDEX_URL='https://pypi.tuna.tsinghua.edu.cn/simple'",
    "`$env:UV_DEFAULT_INDEX='https://pypi.tuna.tsinghua.edu.cn/simple'",
    "`$env:XINFERENCE_VIRTUAL_ENV_SKIP_INSTALLED='1'",
    "`$env:XINFERENCE_HEALTH_CHECK_ATTEMPTS=10",
    "`$env:XINFERENCE_HEALTH_CHECK_INTERVAL=5",
    "xinference-local --host $HostAddress --port $Port"
  ) -join "; "
  Start-Process -FilePath "powershell" -ArgumentList "-NoExit", "-Command", $cmd | Out-Null
  Wait-ForHttp -url $healthUrl
  Write-Host "Xinference server is ready." -ForegroundColor Green
}

function Get-ModelMap {
  return @(
    @{ Alias = "BGE-M3"; ModelName = "bge-m3"; ModelType = "embedding" },
    @{ Alias = "BGE-large-zh"; ModelName = "bge-large-zh-v1.5"; ModelType = "embedding" },
    @{ Alias = "GTE-Qwen"; ModelName = "gte-qwen2-1.5B-instruct"; ModelType = "embedding" }
  )
}

function Get-RunningModelNames {
  try {
    $models = Invoke-RestMethod -Uri "http://${HostAddress}:${Port}/v1/models" -Method Get -TimeoutSec 10
  } catch {
    return @()
  }

  $names = @()
  foreach ($item in ($models.data | Where-Object { $_ })) {
    if ($item.id) { $names += [string]$item.id }
    if ($item.model_name) { $names += [string]$item.model_name }
  }
  return $names
}

function Ensure-ModelLaunched($model) {
  $running = Get-RunningModelNames
  if ($running -contains $model.ModelName) {
    Write-Host "$($model.Alias) already running." -ForegroundColor Green
    return
  }

  Write-Step "Launching $($model.Alias)"
  & xinference launch --endpoint "http://${HostAddress}:${Port}" --model-name $model.ModelName --model-type $model.ModelType
}

Write-Step "Checking prerequisites"
Ensure-Xinference
Ensure-ServerStarted

foreach ($model in Get-ModelMap) {
  Ensure-ModelLaunched -model $model
}

Write-Step "Done"
Write-Host "Xinference base URL: http://${HostAddress}:${Port}/v1" -ForegroundColor Yellow
Write-Host "Recommended AI Platform settings:" -ForegroundColor Yellow
Write-Host "  BGE-M3         -> model=bge-m3, baseUrl=http://${HostAddress}:${Port}/v1, dim=1024"
Write-Host "  BGE-large-zh   -> model=bge-large-zh-v1.5, baseUrl=http://${HostAddress}:${Port}/v1, dim=1024"
Write-Host "  GTE-Qwen       -> model=gte-qwen2-1.5B-instruct, baseUrl=http://${HostAddress}:${Port}/v1, dim=1024"
Write-Host "Local mode API Key can be left empty or set to: test" -ForegroundColor Yellow
