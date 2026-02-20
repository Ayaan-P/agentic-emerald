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

# ── Step 3: Create config ────────────────────────────────────────────────
echo -e "${CYAN}[3/5]${RESET} Config setup..."
if [ -f "config.yaml" ]; then
    echo -e "  ${GREEN}✓ config.yaml already exists (skipping)${RESET}"
else
    cp config.example.yaml config.yaml
    echo -e "  ${GREEN}✓ Created config.yaml from example${RESET}"
    echo ""
    echo -e "  ${YELLOW}⚠  Edit config.yaml before running the daemon.${RESET}"
    echo -e "  ${YELLOW}   Key setting: agent.mode (use 'claude' if you have Claude CLI)${RESET}"
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
echo -e "  1. ${CYAN}Edit config.yaml${RESET} — set your agent mode and emulator host"
echo -e "  2. ${CYAN}Open mGBA${RESET} → load your Pokemon Emerald ROM"
echo -e "  3. ${CYAN}In mGBA:${RESET} Tools → Scripting → load ${BOLD}lua/game_master_v2.lua${RESET}"
echo -e "  4. ${CYAN}Run the daemon:${RESET} ${BOLD}python3 daemon/agentic_emerald.py${RESET}"
echo -e "  5. ${CYAN}Play.${RESET} Maren is watching."
echo ""
echo -e "${BOLD}Docs:${RESET} See README.md for full setup details and troubleshooting."
echo ""
