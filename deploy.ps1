# GitHub に push して Render の自動デプロイを起動する（PowerShell）
# 使い方:
#   .\deploy.ps1
#   .\deploy.ps1 -Message "学びデータとUI修正"
param(
    [string]$Message = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $Message) {
    $Message = "deploy $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
}

git add .
$changes = git status --porcelain
if (-not $changes) {
    Write-Host "変更がありません（コミット・push は行いません）。"
    exit 0
}

git commit -m $Message
if ($LASTEXITCODE -ne 0) {
    Write-Host "git commit に失敗しました。"
    exit $LASTEXITCODE
}

git push
if ($LASTEXITCODE -ne 0) {
    Write-Host "git push に失敗しました。"
    exit $LASTEXITCODE
}

Write-Host "完了: GitHub へ push しました。Render が Auto-Deploy なら数分で本番が更新されます。"
