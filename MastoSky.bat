@echo off
:: MastoSky Launcher para Windows
:: Dá duplo clique neste ficheiro para abrir o MastoSky no teu browser.

title MastoSky
cd /d "%~dp0"

echo ====================================
echo    MastoSky esta a iniciar...   
echo ====================================
echo.
echo A abrir http://127.0.0.1:8000 no teu browser...
echo Podes fechar esta janela para encerrar o servidor.
echo.

:: Abre o browser predefinido na pagina do MastoSky
start "" "http://127.0.0.1:8000"

:: Tenta executar com 'python' ou 'py'
python app.py 2>nul
if %errorlevel% neq 0 (
    py app.py 2>nul
)

if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Nao foi possivel iniciar o MastoSky.
    echo O Python 3 nao foi encontrado no teu sistema.
    echo Podes descarregar e instalar gratuitamente em: https://www.python.org/downloads/
    echo (Certifica-te de marcar a opcao "Add Python to PATH" durante a instalacao).
    echo.
    pause
)

