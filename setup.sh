#!/usr/bin/env bash
# Agentic Emerald — Setup Script
# Installs deps, creates config, verifies environment
# Usage: ./setup.sh

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;91m'
BOLD='\033[1m'
RESET='\033[0m'

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║   Agentic Emerald — Setup            ║${RESET}"
echo -e "${BOLD}${CYAN}║   Invisible GM for Pokemon Emerald   ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════╝${RESET}"
echo ""

# ── Step 1: Python check ────────────────────────────────────────────────
echo -e "${CYAN}[1/5]${RESET} Checking Python..."
if ! command -v python3 &>/dev/null; then
    echo -e "  ${RED}✗ Python 3 not found. Install from https://python.org${RESET}"
    exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "  ${GREEN}✓ Python ${PY_VER}${RESET}"

# ── Step 2: Install dependencies ─────────────────────────────────────────
echo -e "${CYAN}[2/5]${RESET} Installing dependencies..."
pip3 install -r requirements.txt -q
echo -e "  ${GREEN}✓ Dependencies installed${RESET}"

# ── Step 3: Create config (interactive wizard for new installs) ──────────
echo -e "${CYAN}[3/5]${RESET} Config setup..."
if [ -f "config.yaml" ]; then
    echo -e "  ${GREEN}✓ config.yaml already exists (skipping)${RESET}"
else
    cp config.example.yaml config.yaml
    echo -e "  ${GREEN}✓ Created config.yaml from example${RESET}"
    echo ""
    echo -e "  ${BOLD}Quick setup wizard:${RESET}"
    echo -e "  ${CYAN}(Press Enter to accept defaults, or type a value)${RESET}"
    echo ""

    # ── Detect WSL ─────────────────────────────────────────────────────
    IS_WSL=false
    if grep -qi microsoft /proc/version 2>/dev/null || grep -qi wsl /proc/version 2>/dev/null; then
        IS_WSL=true
    fi

    # ── Where is mGBA running? ─────────────────────────────────────────
    if [ "$IS_WSL" = "true" ]; then
        # Try to get Windows host IP from resolv.conf
        WIN_IP=$(grep nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}' | grep -E '^(10\.|172\.|192\.168\.)' | head -1)
        echo -e "  ${YELLOW}WSL detected!${RESET} mGBA is likely running on Windows."
        if [ -n "$WIN_IP" ]; then
            echo -e "  Detected Windows IP: ${CYAN}${WIN_IP}${RESET}"
            echo -n "  Use this as emulator host? [Y/n]: "
            read -r USE_WIN_IP
            if [[ "$USE_WIN_IP" =~ ^[Nn] ]]; then
                echo -n "  Enter emulator host (IP or hostname): "
                read -r EMU_HOST
                EMU_HOST="${EMU_HOST:-127.0.0.1}"
            else
                EMU_HOST="$WIN_IP"
            fi
        else
            echo -e "  ${YELLOW}Could not auto-detect Windows IP.${RESET}"
            echo -e "  Run ${BOLD}ipconfig${RESET} on Windows → look for 'vEthernet (WSL)' IPv4 address"
            echo -n "  Enter emulator host [127.0.0.1]: "
            read -r EMU_HOST
            EMU_HOST="${EMU_HOST:-127.0.0.1}"
        fi
    else
        echo -n "  mGBA running on same machine? [Y/n]: "
        read -r SAME_MACHINE
        if [[ "$SAME_MACHINE" =~ ^[Nn] ]]; then
            echo -n "  Enter mGBA host (IP of the machine running mGBA): "
            read -r EMU_HOST
            EMU_HOST="${EMU_HOST:-127.0.0.1}"
        else
            EMU_HOST="127.0.0.1"
        fi
    fi

    # Apply host to config.yaml
    if [ "$EMU_HOST" != "127.0.0.1" ]; then
        sed -i "s/host: \"127.0.0.1\"/host: \"${EMU_HOST}\"/" config.yaml
        echo -e "  ${GREEN}✓ Set emulator.host: ${EMU_HOST}${RESET}"
    else
        echo -e "  ${GREEN}✓ emulator.host: 127.0.0.1 (localhost)${RESET}"
    fi

    echo ""

    # ── Agent mode ─────────────────────────────────────────────────────
    DETECTED_AGENTS=()
    if command -v claude &>/dev/null; then
        DETECTED_AGENTS+=("claude (found: $(which claude))")
    fi
    if command -v codex &>/dev/null; then
        DETECTED_AGENTS+=("codex (found: $(which codex))")
    fi
    if command -v clawdbot &>/dev/null; then
        DETECTED_AGENTS+=("clawdbot (found: $(which clawdbot))")
    fi
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        DETECTED_AGENTS+=("direct (ANTHROPIC_API_KEY is set)")
    fi

    if [ ${#DETECTED_AGENTS[@]} -gt 0 ]; then
        echo -e "  Detected agent options:"
        for agent in "${DETECTED_AGENTS[@]}"; do
            echo -e "    ${GREEN}✓${RESET} $agent"
        done
        echo ""
    fi

    echo -e "  Agent modes: ${BOLD}claude${RESET} | codex | direct | clawdbot"
    echo -n "  Agent mode [claude]: "
    read -r AGENT_MODE
    AGENT_MODE="${AGENT_MODE:-claude}"

    sed -i "s/mode: \"claude\"/mode: \"${AGENT_MODE}\"/" config.yaml
    echo -e "  ${GREEN}✓ Set agent.mode: ${AGENT_MODE}${RESET}"

    echo ""
    echo -e "  ${GREEN}✓ config.yaml ready${RESET}"
    echo -e "  ${DIM}  You can edit config.yaml manually to change any setting.${RESET}"
    echo ""
fi

# ── Step 4: Create required directories ─────────────────────────────────
echo -e "${CYAN}[4/5]${RESET} Creating directories..."
mkdir -p agent/state agent/memory state memory
touch agent/memory/PLAYTHROUGH.md 2>/dev/null || true
echo -e "  ${GREEN}✓ agent/state, agent/memory, state, memory${RESET}"

# ── Step 5: Check agent (Claude CLI or API key) ──────────────────────────
echo -e "${CYAN}[5/5]${RESET} Checking AI agent..."
AGENT_OK=false

if command -v claude &>/dev/null; then
    echo -e "  ${GREEN}✓ Claude CLI found — use mode: 'claude' in config.yaml${RESET}"
    AGENT_OK=true
fi

if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo -e "  ${GREEN}✓ ANTHROPIC_API_KEY set — can use mode: 'direct'${RESET}"
    AGENT_OK=true
fi

if command -v clawdbot &>/dev/null; then
    echo -e "  ${GREEN}✓ Clawdbot found — can use mode: 'clawdbot'${RESET}"
    AGENT_OK=true
fi

if [ "$AGENT_OK" = false ]; then
    echo -e "  ${YELLOW}⚠  No AI agent found.${RESET}"
    echo -e "  ${YELLOW}   Options:${RESET}"
    echo -e "  ${YELLOW}   • Install Claude CLI (recommended if you have Claude Max)${RESET}"
    echo -e "  ${YELLOW}   • Set ANTHROPIC_API_KEY for direct API access${RESET}"
fi

# ── Done ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}Setup complete!${RESET}"
echo ""
echo -e "${BOLD}Next steps:${RESET}"
echo -e "  1. ${CYAN}Open mGBA${RESET} → load your Pokemon Emerald ROM"
echo -e "  2. ${CYAN}In mGBA:${RESET} Tools → Scripting → load ${BOLD}lua/game_master_v2.lua${RESET}"
echo -e "  3. ${CYAN}Validate your setup:${RESET} ${BOLD}python3 daemon/agentic_emerald.py --check${RESET}"
echo -e "  4. ${CYAN}Run the daemon:${RESET} ${BOLD}python3 daemon/agentic_emerald.py${RESET}"
echo -e "  5. ${CYAN}Play.${RESET} Maren is watching."
echo ""
echo -e "${BOLD}Docs:${RESET} See README.md for full setup details and troubleshooting."
echo -e "${BOLD}Stuck?${RESET} Run: ${BOLD}python3 daemon/agentic_emerald.py --check${RESET} for diagnostics"
echo ""
