#!/usr/bin/env bash
# ==============================================================================
# MastoSky Installer (macOS & Linux)
# https://github.com/gjmcosta/MastoSky
#
# Uso:
#   curl -fsSL https://raw.githubusercontent.com/gjmcosta/MastoSky/main/install.sh | bash
# ==============================================================================

set -e

BOLD="\033[1m"
GREEN="\033[0;32m"
CYAN="\033[0;36m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
RESET="\033[0m"

echo -e "${BOLD}${CYAN}"
echo "=========================================================="
echo "          🌌 A instalar o MastoSky...                     "
echo "=========================================================="
echo -e "${RESET}"

# 1. Verificar Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}[ERRO] Python 3 não encontrado no teu sistema.${RESET}"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo -e "${YELLOW}No macOS podes instalar com:${RESET} xcode-select --install"
        echo -e "${YELLOW}Ou descarregar em:${RESET} https://www.python.org/downloads/"
    else
        echo -e "${YELLOW}No Linux instala com:${RESET} sudo apt install python3 (ou o gestor da tua distro)"
    fi
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "${GREEN}✓ Python ${PY_VER} detetado.${RESET}"

INSTALL_DIR="$HOME/.mastosky/app"
mkdir -p "$HOME/.mastosky"

# 2. Descarregar ou atualizar o MastoSky
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "${CYAN}→ A atualizar instalação existente em ${INSTALL_DIR}...${RESET}"
    cd "$INSTALL_DIR"
    git pull --ff-only || (git fetch origin main && git reset --hard origin/main)
else
    echo -e "${CYAN}→ A transferir MastoSky para ${INSTALL_DIR}...${RESET}"
    if command -v git >/dev/null 2>&1; then
        rm -rf "$INSTALL_DIR"
        git clone https://github.com/gjmcosta/MastoSky.git "$INSTALL_DIR"
    else
        mkdir -p "$INSTALL_DIR"
        curl -fsSL https://github.com/gjmcosta/MastoSky/archive/refs/heads/main.tar.gz | tar -xz --strip-components=1 -C "$INSTALL_DIR"
    fi
fi

cd "$INSTALL_DIR"

# 3. Criar atalhos no sistema
if [[ "$OSTYPE" == "darwin"* ]]; then
    # Atalho no Ambiente de Trabalho (.command)
    DESKTOP_DIR="$HOME/Desktop"
    if [ -d "$DESKTOP_DIR" ]; then
        cat << 'EOF' > "$DESKTOP_DIR/MastoSky.command"
#!/bin/bash
cd "$HOME/.mastosky/app"
python3 app.py --open
EOF
        chmod +x "$DESKTOP_DIR/MastoSky.command"
        echo -e "${GREEN}✓ Atalho criado no Ambiente de Trabalho: MastoSky.command${RESET}"
    fi

    # Criar MastoSky.app em ~/Applications para aparecer no Spotlight / Launchpad
    USER_APPS="$HOME/Applications"
    mkdir -p "$USER_APPS"
    if command -v osacompile >/dev/null 2>&1; then
        osacompile -o "$USER_APPS/MastoSky.app" -e 'do shell script "bash \"'"$INSTALL_DIR"'/MastoSky.command\" >/dev/null 2>&1 &"' 2>/dev/null || true
        # Adicionar ícone se disponível
        if [ -f "$INSTALL_DIR/brand/favicon.svg" ] && [ -d "$USER_APPS/MastoSky.app" ]; then
            echo -e "${GREEN}✓ Aplicação criada em ~/Applications/MastoSky.app (acessível no Spotlight)${RESET}"
        fi
    fi
else
    # Linux Desktop Entry
    DESKTOP_ENTRY_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_ENTRY_DIR"
    cat << EOF > "$DESKTOP_ENTRY_DIR/mastosky.desktop"
[Desktop Entry]
Type=Application
Name=MastoSky
Comment=Cliente unificado Bluesky e Mastodon
Exec=python3 $INSTALL_DIR/app.py --open
Icon=$INSTALL_DIR/brand/favicon.svg
Terminal=false
Categories=Network;Chat;
EOF
    chmod +x "$DESKTOP_ENTRY_DIR/mastosky.desktop"
    echo -e "${GREEN}✓ Atalho criado no menu de aplicações (mastosky.desktop)${RESET}"
fi

echo ""
echo -e "${BOLD}${GREEN}=========================================================="
echo "          🎉 MastoSky instalado com sucesso!              "
echo "=========================================================="
echo -e "${RESET}"
echo -e "A iniciar servidor e a abrir o teu browser..."
echo ""

# Iniciar MastoSky
exec python3 "$INSTALL_DIR/app.py" --open
