# Bring up the Solstice local stack (Windows PowerShell). See up.sh for details.
#   $env:TF_VAR_agent_port = 18080; $env:TF_VAR_enable_web = "true"; .\infra\up.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Talk to the same Docker engine as the docker CLI, unless the caller chose explicitly.
if (-not $env:TF_VAR_docker_host) {
    $dockerHost = docker context inspect --format '{{.Endpoints.docker.Host}}'
    if ($LASTEXITCODE -eq 0 -and $dockerHost) { $env:TF_VAR_docker_host = "$dockerHost".Trim() }
}

if (-not $env:TF_VAR_ollama_mode) {
    docker run --rm --gpus all busybox true *> $null
    if ($LASTEXITCODE -eq 0) {
        $env:TF_VAR_ollama_mode = "container"
    } else {
        Write-Warning "Docker GPU passthrough unavailable -> using host Ollama (TF_VAR_ollama_mode=host)"
        $env:TF_VAR_ollama_mode = "host"
    }
}

foreach ($stage in @("01-platform", "02-apps")) {
    Write-Host "==> terraform apply: $stage"
    terraform "-chdir=$here/terraform/$stage" init -input=false | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "terraform init failed in $stage" }
    terraform "-chdir=$here/terraform/$stage" apply -input=false -auto-approve
    if ($LASTEXITCODE -ne 0) { throw "terraform apply failed in $stage" }
}

terraform "-chdir=$here/terraform/02-apps" output
Write-Host "Service token (local scripts):  terraform -chdir=infra/terraform/02-apps output -raw service_token"
