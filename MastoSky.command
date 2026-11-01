#!/bin/bash
# MastoSky Launcher para macOS
# Dá duplo clique neste ficheiro para abrir o MastoSky no teu browser.

cd "$(dirname "$0")"

echo "===================================="
echo "   🌌 MastoSky está a iniciar...   "
echo "===================================="
echo ""
echo "A abrir http://127.0.0.1:8000 no teu browser..."
echo "Podes fechar esta janela ou premir Ctrl+C para encerrar o servidor."
echo ""

# Executa o servidor Python e abre o browser predefinido
python3 app.py --open

