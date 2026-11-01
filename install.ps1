# ==============================================================================
# MastoSky Installer (Windows PowerShell)
# https://github.com/gjmcosta/MastoSky
#
# Uso:
#   irm https://raw.githubusercontent.com/gjmcosta/MastoSky/main/install.ps1 | iex
# ==============================================================================

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "          🌌 A instalar o MastoSky para Windows...       " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verificar Python 3
$pythonCmd = $null
if (Get-Command "python" -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command "py" -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
}

if (-not $pythonCmd) {
    Write-Host "[ERRO] Python 3 nao foi encontrado no teu computador." -ForegroundColor Red
    Write-Host "Podes instalar facilmente a partir da Microsoft Store ou em:" -ForegroundColor Yellow
    Write-Host "https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "(Certifica-te de marcar a opcao 'Add Python to PATH')." -ForegroundColor Yellow
    exit 1
}

Write-Host "✓ Python encontrado ($pythonCmd)." -ForegroundColor Green

# 2. Definir pastas
$installDir = "$env:USERPROFILE\.mastosky\app"
$null = New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.mastosky"

# 3. Descarregar ou atualizar MastoSky
if (Test-Path "$installDir\.git") {
    Write-Host "→ A atualizar instalacao existente..." -ForegroundColor Cyan
    Set-Location $installDir
    git pull --ff-only
} else {
    Write-Host "→ A transferir MastoSky para $installDir..." -ForegroundColor Cyan
    if (Get-Command "git" -ErrorAction SilentlyContinue) {
        if (Test-Path $installDir) { Remove-Item -Recurse -Force $installDir }
        git clone https://github.com/gjmcosta/MastoSky.git $installDir
    } else {
        $zipUrl = "https://github.com/gjmcosta/MastoSky/archive/refs/heads/main.zip"
        $zipPath = "$env:TEMP\mastosky_main.zip"
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
        Expand-Archive -LiteralPath $zipPath -DestinationPath "$env:TEMP\mastosky_temp" -Force
        if (Test-Path $installDir) { Remove-Item -Recurse -Force $installDir }
        Move-Item -Path "$env:TEMP\mastosky_temp\MastoSky-main" -Destination $installDir
        Remove-Item -Force $zipPath
        Remove-Item -Recurse -Force "$env:TEMP\mastosky_temp"
    }
}

# 4. Criar atalho no Ambiente de Trabalho
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "MastoSky.lnk"
$targetBat = Join-Path $installDir "MastoSky.bat"

$wshell = New-Object -ComObject WScript.Shell
$shortcut = $wshell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetBat
$shortcut.WorkingDirectory = $installDir
$shortcut.Description = "MastoSky - Cliente unificado Bluesky e Mastodon"
$shortcut.Save()

Write-Host "✓ Atalho criado no Ambiente de Trabalho: MastoSky.lnk" -ForegroundColor Green
Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "          🎉 MastoSky instalado com sucesso!              " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "A iniciar servidor e a abrir o teu browser..."

# 5. Iniciar
Set-Location $installDir
Start-Process -FilePath $targetBat

