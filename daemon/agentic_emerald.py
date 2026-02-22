#!/usr/bin/env python3
"""
Agentic Emerald Daemon - Event-driven AI Game Master
Connects to mGBA, observes gameplay, and sends story events to an AI agent
that decides on invisible interventions.

Supports two modes:
- clawdbot: Uses Clawdbot CLI for agent management (recommended)
- direct: Calls Anthropic API directly (no dependencies)
"""
import socket
import json
import time
import select
import subprocess
import os
import sys
import threading
import uuid
import argparse
import shutil
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required. Install with: pip install pyyaml")
    sys.exit(1)

# Optional: Anthropic SDK for direct mode
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


def load_config(config_path: Path) -> dict:
    """Load configuration from YAML file"""
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        print("Copy config.example.yaml to config.yaml and edit it.")
        sys.exit(1)
    
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_species_names(species_file: Path) -> dict:
    """Load Pokemon species names from JSON"""
    names = {}
    try:
        with open(species_file) as f:
            data = json.load(f)
        for species_id, name in data.get('species', {}).items():
            names[int(species_id)] = name
        print(f"[SPECIES] Loaded {len(names)} Pokemon")
    except Exception as e:
        print(f"[SPECIES] Warning: {e}")
    return names


def _is_wsl() -> bool:
    """Detect if running inside WSL (Windows Subsystem for Linux)."""
    try:
        with open('/proc/version') as f:
            content = f.read().lower()
            return 'microsoft' in content or 'wsl' in content
    except Exception:
        return False


def _get_windows_ip() -> str:
    """Get the Windows host IP from WSL's /etc/resolv.conf nameserver."""
    try:
        result = subprocess.run(['cat', '/etc/resolv.conf'], capture_output=True, text=True, timeout=2)
        for line in result.stdout.split('\n'):
            if line.startswith('nameserver'):
                ip = line.split()[1]
                # Only return RFC 1918 addresses (Windows host is always private)
                if ip.startswith(('10.', '172.', '192.168.')):
                    return ip
    except Exception:
        pass
    return ''


def check_setup(config_path: Path):
    """
    Validate the full setup without starting the daemon.
    Run with: python3 daemon/agentic_emerald.py --check
    """
    C = Colors
    errors = []
    warnings = []

    print(f"\n{C.BOLD}{C.CYAN}╔══════════════════════════════════════════════╗")
    print(f"║  Agentic Emerald — Setup Check               ║")
    print(f"╚══════════════════════════════════════════════╝{C.RESET}\n")

    # ── 1. Config file ────────────────────────────────────────────────────
    print(f"{C.BOLD}Config{C.RESET}")
    if not config_path.exists():
        print(f"  {C.RED}✗ config.yaml not found: {config_path}{C.RESET}")
        print(f"  {C.DIM}  → Run: cp config.example.yaml config.yaml  then edit it{C.RESET}")
        errors.append("config_missing")
        _print_check_result(errors, warnings)
        return
    else:
        print(f"  {C.GREEN}✓ {config_path}{C.RESET}")

    try:
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)
        print(f"  {C.GREEN}✓ Parsed OK{C.RESET}")
    except Exception as e:
        print(f"  {C.RED}✗ Parse error: {e}{C.RESET}")
        errors.append("config_invalid")
        _print_check_result(errors, warnings)
        return

    # ── 2. Socket connection ──────────────────────────────────────────────
    print(f"\n{C.BOLD}mGBA Connection{C.RESET}")
    emu = config.get('emulator', {})
    host = emu.get('host', '127.0.0.1')
    port = emu.get('port', 8888)
    print(f"  Configured: {C.CYAN}{host}:{port}{C.RESET}")

    try:
        s = socket.socket()
        s.settimeout(3)
        s.connect((host, port))
        s.close()
        print(f"  {C.GREEN}✓ mGBA connected — Lua script is running{C.RESET}")
    except ConnectionRefusedError:
        print(f"  {C.YELLOW}⚠  mGBA not reachable (connection refused){C.RESET}")
        print(f"  {C.DIM}  → Open mGBA → load ROM → Tools → Scripting → load lua/game_master_v2.lua{C.RESET}")
        if host == '127.0.0.1' and _is_wsl():
            win_ip = _get_windows_ip()
            hint = f' Try host: "{win_ip}"' if win_ip else ''
            print(f"  {C.YELLOW}  WSL detected: mGBA may be on Windows, not localhost.{hint}{C.RESET}")
            print(f"  {C.DIM}  See README: WSL Setup section{C.RESET}")
        warnings.append("mgba_not_connected")
    except socket.timeout:
        print(f"  {C.YELLOW}⚠  Connection timed out{C.RESET}")
        if _is_wsl() and host == '127.0.0.1':
            win_ip = _get_windows_ip()
            print(f"  {C.YELLOW}  WSL + localhost: mGBA likely on Windows.{C.RESET}")
            if win_ip:
                print(f"  {C.YELLOW}  → Set emulator.host: \"{win_ip}\" in config.yaml{C.RESET}")
        warnings.append("mgba_timeout")
    except Exception as e:
        print(f"  {C.RED}✗ Socket error: {e}{C.RESET}")
        warnings.append("mgba_error")

    # ── 3. Agent ──────────────────────────────────────────────────────────
    print(f"\n{C.BOLD}AI Agent{C.RESET}")
    agent_cfg = config.get('agent', {})
    agent_mode = agent_cfg.get('mode', 'claude')
    print(f"  Mode: {C.CYAN}{agent_mode}{C.RESET}")

    if agent_mode == 'claude':
        if shutil.which('claude'):
            print(f"  {C.GREEN}✓ Claude CLI found ({shutil.which('claude')}){C.RESET}")
        else:
            print(f"  {C.RED}✗ Claude CLI not found in PATH{C.RESET}")
            print(f"  {C.DIM}  → Install: npm install -g @anthropic-ai/claude-code{C.RESET}")
            errors.append("claude_not_found")
    elif agent_mode == 'codex':
        if shutil.which('codex'):
            print(f"  {C.GREEN}✓ Codex CLI found{C.RESET}")
        else:
            print(f"  {C.RED}✗ Codex CLI not found{C.RESET}")
            errors.append("codex_not_found")
    elif agent_mode == 'direct':
        api_key = agent_cfg.get('api_key', '') or os.environ.get('ANTHROPIC_API_KEY', '')
        if api_key:
            print(f"  {C.GREEN}✓ API key found{C.RESET}")
        else:
            print(f"  {C.RED}✗ No API key — set api_key in config or ANTHROPIC_API_KEY env var{C.RESET}")
            errors.append("api_key_missing")
    elif agent_mode == 'clawdbot':
        if shutil.which('clawdbot'):
            print(f"  {C.GREEN}✓ Clawdbot found ({shutil.which('clawdbot')}){C.RESET}")
        else:
            print(f"  {C.RED}✗ Clawdbot not found{C.RESET}")
            print(f"  {C.DIM}  → Install: npm install -g clawdbot{C.RESET}")
            errors.append("clawdbot_not_found")
    else:
        print(f"  {C.YELLOW}⚠  Unknown agent mode: {agent_mode}{C.RESET}")
        warnings.append("unknown_agent_mode")

    # ── 4. Agent workspace ───────────────────────────────────────────────
    print(f"\n{C.BOLD}Agent Workspace{C.RESET}")
    base_path = config_path.parent
    workspace = base_path / agent_cfg.get('workspace', './agent')
    agents_md = workspace / 'AGENTS.md'
    gm_narrative = workspace / 'GM_NARRATIVE.md'

    if workspace.exists():
        print(f"  {C.GREEN}✓ Directory: {workspace}{C.RESET}")
        if agents_md.exists():
            print(f"  {C.GREEN}✓ AGENTS.md{C.RESET}")
        else:
            print(f"  {C.YELLOW}⚠  AGENTS.md missing{C.RESET}")
            warnings.append("agents_md_missing")
        if gm_narrative.exists():
            print(f"  {C.GREEN}✓ GM_NARRATIVE.md{C.RESET}")
        else:
            print(f"  {C.YELLOW}⚠  GM_NARRATIVE.md missing{C.RESET}")
            warnings.append("gm_narrative_missing")
    else:
        print(f"  {C.RED}✗ Workspace not found: {workspace}{C.RESET}")
        print(f"  {C.DIM}  → Run: ./setup.sh{C.RESET}")
        errors.append("workspace_missing")

    # ── 5. Species data ──────────────────────────────────────────────────
    print(f"\n{C.BOLD}Data Files{C.RESET}")
    paths = config.get('paths', {})
    species_file = base_path / paths.get('species_file', './data/emerald_species.json')
    if species_file.exists():
        print(f"  {C.GREEN}✓ Species data: {species_file.name}{C.RESET}")
    else:
        print(f"  {C.YELLOW}⚠  Species data not found: {species_file}{C.RESET}")
        warnings.append("species_missing")

    playthrough = base_path / 'memory' / 'PLAYTHROUGH.md'
    if playthrough.exists():
        size = playthrough.stat().st_size
        print(f"  {C.GREEN}✓ PLAYTHROUGH.md ({size} bytes){C.RESET}")
    else:
        print(f"  {C.DIM}  PLAYTHROUGH.md not found (will be created on first run){C.RESET}")

    # ── Summary ──────────────────────────────────────────────────────────
    _print_check_result(errors, warnings)


def _print_check_result(errors: list, warnings: list):
    C = Colors
    print(f"\n  {'─' * 44}")
    if errors:
        print(f"  {C.RED}{C.BOLD}✗ {len(errors)} error(s) — fix these before running{C.RESET}")
        sys.exit(1)
    elif warnings:
        print(f"  {C.YELLOW}⚠  {len(warnings)} warning(s) — OK to run, but check the notes above{C.RESET}")
        print(f"  {C.GREEN}✓ Run: python3 daemon/agentic_emerald.py{C.RESET}")
    else:
        print(f"  {C.GREEN}{C.BOLD}✓ All checks passed!{C.RESET}")
        print(f"  {C.GREEN}✓ Run: python3 daemon/agentic_emerald.py{C.RESET}")
    print()


# Common move names for logging
MOVE_NAMES = {
    10: "Scratch", 13: "Razor Wind", 14: "Swords Dance", 15: "Cut",
    33: "Tackle", 45: "Growl", 52: "Ember", 53: "Flamethrower",
    64: "Peck", 83: "Fire Spin", 88: "Rock Throw", 89: "Earthquake",
    116: "Focus Energy", 163: "Slash", 172: "Flame Wheel",
    224: "Mega Kick", 241: "Sunny Day", 249: "Rock Smash",
    257: "Heat Wave", 299: "Blaze Kick", 315: "Overheat",
    394: "Flare Blitz", 55: "Water Gun", 57: "Surf", 58: "Ice Beam",
    71: "Absorb", 72: "Mega Drain", 202: "Giga Drain",
}

# ANSI colors for terminal output
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


class PokemonGM:
    def __init__(self, config: dict, base_path: Path):
        self.config = config
        self.base_path = base_path
        
        # Connection settings
        emu_config = config.get('emulator', {})
        self.socket_host = emu_config.get('host', '127.0.0.1')
        self.socket_port = emu_config.get('port', 8888)
        
        # Agent settings (load early - needed for paths)
        agent_config = config.get('agent', {})
        
        # Paths
        paths = config.get('paths', {})
        # Agent workspace state dir (where agent writes gm_response.txt)
        agent_workspace = base_path / agent_config.get('workspace', '../agent')
        self.state_dir = agent_workspace / 'state'
        self.memory_dir = base_path / paths.get('memory_dir', './memory')
        self.events_file = self.state_dir / 'events.jsonl'
        self.response_file = self.state_dir / 'gm_response.txt'
        
        # Species names
        species_file = base_path / paths.get('species_file', './data/emerald_species.json')
        self.species_names = load_species_names(species_file)
        
        # Agent settings
        self.agent_id = agent_config.get('id', 'pokemon-gm')
        self.agent_mode = agent_config.get('mode', 'clawdbot')  # 'clawdbot' or 'direct'
        self.agent_model = agent_config.get('model', 'claude-sonnet-4-20250514')
        self.api_key = agent_config.get('api_key', os.environ.get('ANTHROPIC_API_KEY', ''))
        
        # Load system prompt for non-clawdbot modes
        agent_workspace = base_path / agent_config.get('workspace', './agent')
        
        if self.agent_mode == 'direct':
            if not HAS_ANTHROPIC:
                print("Direct mode requires anthropic package. Install with: pip install anthropic")
                sys.exit(1)
            if not self.api_key:
                print("Direct mode requires api_key in config or ANTHROPIC_API_KEY env var")
                sys.exit(1)
            self.anthropic_client = anthropic.Anthropic(api_key=self.api_key)
            self.system_prompt = self._load_system_prompt(agent_workspace)
            self.conversation_history = []  # For multi-turn context
        elif self.agent_mode in ('claude', 'codex'):
            self.system_prompt = self._load_system_prompt(agent_workspace)
        
        # Session settings
        session_config = config.get('session', {})
        if session_config.get('persistent', False):
            session_file = base_path / session_config.get('session_file', './state/session_id.txt')
            if session_file.exists():
                self.session_id = session_file.read_text().strip()
            else:
                self.session_id = f"gm-{uuid.uuid4().hex[:8]}"
                session_file.parent.mkdir(parents=True, exist_ok=True)
                session_file.write_text(self.session_id)
        else:
            self.session_id = f"gm-{uuid.uuid4().hex[:8]}"
        
        # Dytto settings
        dytto_config = config.get('dytto', {})
        self.dytto_enabled = dytto_config.get('enabled', False)
        self.dytto_script = dytto_config.get('script_path', '')
        
        # Session persistence settings
        session_config = config.get('session', {})
        self.session_persistent = session_config.get('persistent', False)
        self.session_file = base_path / session_config.get('session_file', './state/session_id.txt')
        self.session_history_file = self.state_dir / 'session.json'
        self.session_history = []
        
        # Runtime state
        self.sock = None
        self.connected = False
        self.agent_busy = False
        self.pending_events = []
        self.skipped_events = []  # Accumulate low-uncertainty events for context
        self.current_state = {}  # Latest game state for helpers
        self.move_usage = {}  # {moveId: count} for mastery tracking
        
        # Stats
        self.battles_won = 0
        self.pokemon_caught = 0
        self.close_calls = 0
        self.session_start = time.time()
        
        # Reward visibility tracking (Maren impact system)
        self.reward_history = []       # Recent reward types: 'visible', 'ev', 'none'
        self.ev_drought_count = 0      # Consecutive EV-only / no-action rewards
        self.session_visible_rewards = 0  # Visible rewards this session
        
        # Battle tracking
        self.battle_history = []
        self.battle_buffer = []
        self.in_battle = False
        self.battle_start_time = None
        self.battle_start_hp = {}
        self.battle_start_levels = {}
        self.trainer_encounters = {}  # Track trainer battles for rematch detection {enemy_species_level: [timestamps]}
        
        # Ensure directories exist
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        # Load session history if persistent mode is enabled
        if self.session_persistent:
            self._load_session_history()
    
    def _load_system_prompt(self, agent_workspace: Path) -> str:
        """Load system prompt from agent workspace files (for direct mode)"""
        prompt_parts = []
        
        # Load in order of importance
        files = ['AGENTS.md', 'GM_NARRATIVE.md', 'GM_INSTRUCTIONS.md']
        for filename in files:
            filepath = agent_workspace / filename
            if filepath.exists():
                content = filepath.read_text()
                prompt_parts.append(f"# {filename}\n\n{content}")
        
        # Load playthrough memory if exists
        playthrough = self.memory_dir / 'PLAYTHROUGH.md'
        if playthrough.exists():
            content = playthrough.read_text()
            prompt_parts.append(f"# Current Playthrough Memory\n\n{content}")
        
        return "\n\n---\n\n".join(prompt_parts)
    
    def _load_session_history(self):
        """Load previous session history from file if it exists"""
        if self.session_history_file.exists():
            try:
                with open(self.session_history_file) as f:
                    data = json.load(f)
                    self.session_history = data.get('history', [])
                    self.log(f"📜 Loaded {len(self.session_history)} previous session events")
            except Exception as e:
                self.log(f"⚠️ Failed to load session history: {e}")
                self.session_history = []
        else:
            self.log("📝 Starting new session")
    
    def _save_session_history(self):
        """Save session history to file for next run"""
        if self.session_persistent:
            try:
                session_data = {
                    'started_at': datetime.fromtimestamp(self.session_start).isoformat(),
                    'history': self.session_history,
                    'stats': {
                        'battles_won': self.battles_won,
                        'pokemon_caught': self.pokemon_caught,
                        'close_calls': self.close_calls
                    }
                }
                with open(self.session_history_file, 'w') as f:
                    json.dump(session_data, f, indent=2)
            except Exception as e:
                self.log(f"⚠️ Failed to save session history: {e}")
    
    def _add_to_session_history(self, event_type: str, agent_prompt: str, agent_response: str):
        """Record an agent interaction in session history"""
        if self.session_persistent:
            self.session_history.append({
                'timestamp': datetime.now().isoformat(),
                'event_type': event_type,
                'prompt': agent_prompt,
                'response': agent_response
            })
            # Save after each interaction
            self._save_session_history()
    
    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{Colors.DIM}{ts}{Colors.RESET}  {msg}")
    
    def print_banner(self):
        """Print startup banner"""
        C = Colors
        print(f"""
{C.BOLD}{C.MAGENTA}╔══════════════════════════════════════════════════════════╗
║  {C.CYAN}▄▀█ █▀▀ █▀▀ █▄ █ ▀█▀ █ █▀▀   █▀▀ █▀▄▀█ █▀▀ █▀█ ▄▀█ █   █▀▄{C.MAGENTA}  ║
║  {C.CYAN}█▀█ █▄█ ██▄ █ ▀█  █  █ █▄▄   ██▄ █ ▀ █ ██▄ █▀▄ █▀█ █▄▄ █▄▀{C.MAGENTA}  ║
║                                                            ║
║  {C.WHITE}AI Game Master • Narrative-Driven Pokemon{C.MAGENTA}                 ║
╚══════════════════════════════════════════════════════════╝{C.RESET}
""")
    
    def get_species_name(self, species_id: int) -> str:
        if species_id <= 0:
            return "???"
        return self.species_names.get(species_id, f"Pokemon #{species_id}")
    
    def format_party(self, party: list) -> str:
        if not party:
            return "Empty"
        parts = []
        for p in party:
            name = self.get_species_name(p.get('species', 0))
            level = p.get('level', '?')
            hp = p.get('current_hp', 0)
            max_hp = p.get('max_hp', 0)
            parts.append(f"{name} L{level} ({hp}/{max_hp})")
        return ", ".join(parts)
    
    def get_party_pokemon_name(self, slot: int) -> str:
        """Get Pokemon name from current party by slot"""
        try:
            party = self.current_state.get('party', [])
            if 0 <= slot < len(party):
                species = party[slot].get('species', 0)
                return self.get_species_name(species)
        except:
            pass
        return f"Pokemon #{slot}"
    
    def get_readable_action(self, action_cmd: str) -> str:
        """Convert GM command to human-readable description"""
        import re
        
        stat_names = {
            'hp': 'HP', 'atk': 'Attack', 'attack': 'Attack',
            'def': 'Defense', 'defense': 'Defense',
            'spa': 'Sp. Atk', 'spatk': 'Sp. Atk', 'sp_attack': 'Sp. Atk',
            'spd': 'Sp. Def', 'spdef': 'Sp. Def', 'sp_defense': 'Sp. Def',
            'spe': 'Speed', 'speed': 'Speed'
        }
        
        try:
            # GM.addEVs(slot, stat, amount)
            match = re.search(r'GM\.addEVs\((\d+),\s*["\']?(\w+)["\']?,\s*(\d+)\)', action_cmd)
            if match:
                slot, stat, amount = match.groups()
                pokemon = self.get_party_pokemon_name(int(slot))
                stat_name = stat_names.get(stat.lower(), stat)
                return f"{pokemon} gains +{amount} {stat_name} training"
            
            # GM.healParty()
            if 'GM.healParty()' in action_cmd:
                return "Party fully restored!"
            
            # GM.teachMove(slot, moveId, moveSlot)
            match = re.search(r'GM\.teachMove\((\d+),\s*(\d+)', action_cmd)
            if match:
                slot, move_id = match.groups()
                pokemon = self.get_party_pokemon_name(int(slot))
                move_name = MOVE_NAMES.get(int(move_id), "new move")
                return f"{pokemon} learned {move_name}!"
            
            # GM.giveItem(slot, itemId)
            match = re.search(r'GM\.giveItem\((\d+),\s*(\d+)\)', action_cmd)
            if match:
                slot, item_id = match.groups()
                pokemon = self.get_party_pokemon_name(int(slot))
                return f"{pokemon} received an item"
            
            # GM.addExperience(slot, amount)
            match = re.search(r'GM\.addExperience\((\d+),\s*(\d+)\)', action_cmd)
            if match:
                slot, amount = match.groups()
                pokemon = self.get_party_pokemon_name(int(slot))
                return f"{pokemon} gains +{amount} bonus EXP"
            
            # GM.setFriendship(slot, value)
            match = re.search(r'GM\.setFriendship\((\d+),\s*(\d+)\)', action_cmd)
            if match:
                slot, value = match.groups()
                pokemon = self.get_party_pokemon_name(int(slot))
                return f"{pokemon}'s bond strengthens"
            
            # Fallback: extract function name
            match = re.search(r'GM\.(\w+)\(', action_cmd)
            if match:
                return f"GM.{match.group(1)}()"
                
        except Exception:
            pass
        
        return action_cmd[:50]
    
    def connect(self) -> bool:
        C = Colors
        try:
            self.sock = socket.socket()
            self.sock.settimeout(5)
            self.sock.connect((self.socket_host, self.socket_port))
            self.sock.setblocking(False)
            self.connected = True
            self.log(f"{C.GREEN}● Connected{C.RESET} to mGBA on {C.CYAN}{self.socket_host}:{self.socket_port}{C.RESET}")
            return True
        except Exception as e:
            self.log(f"{C.RED}✗ Connection failed:{C.RESET} {e}")
            self.connected = False
            return False
    
    def write_event(self, event_type: str, data: dict):
        event = {"time": datetime.now().isoformat(), "type": event_type, **data}
        with open(self.events_file, 'a') as f:
            f.write(json.dumps(event) + "\n")
    
    def detect_trainer_rematch(self, enemy_species: int, enemy_level: int) -> bool:
        """
        Detect if this trainer battle is likely a rematch.
        Uses heuristic: if same species+level encountered before within 30 minutes, it's a rematch.
        """
        key = f"{enemy_species}_{enemy_level}"
        now = time.time()
        
        if key not in self.trainer_encounters:
            self.trainer_encounters[key] = []
        
        # Find previous encounters within 30 minutes
        recent_encounters = [t for t in self.trainer_encounters[key] if now - t < 1800]  # 30 min
        is_rematch = len(recent_encounters) > 0
        
        # Record this encounter
        self.trainer_encounters[key].append(now)
        
        # Cleanup old encounters (keep last 10)
        self.trainer_encounters[key] = self.trainer_encounters[key][-10:]
        
        return is_rematch
    
    def score_event_uncertainty(self, event_type: str, context: dict) -> float:
        """
        Score event uncertainty (0-1) to decide if agent invocation is needed.
        Higher uncertainty = more likely to invoke agent.
        
        Based on CATTS framework: allocate compute to high-uncertainty decisions.
        
        Returns: uncertainty score (0-1)
        """
        # High uncertainty — always invoke
        if event_type in ('BADGE_OBTAINED', 'TRAINER_REMATCH'):
            return 1.0
        
        # Battle outcomes — depends on context
        if event_type == 'BATTLE_SUMMARY':
            buffer = context.get('buffer', [])
            
            # Extract battle metadata
            is_trainer = False
            is_close = False
            for event in buffer:
                if event.get('event') == 'START':
                    is_trainer = event.get('is_trainer', False)
                elif event.get('event') == 'END':
                    is_close = event.get('was_close', False)
            
            # Trainer battles are high-uncertainty (narrative implications)
            if is_trainer:
                return 0.9 if is_close else 0.7
            
            # Wild battle, not close → low uncertainty (routine grinding)
            if not is_close:
                return 0.2
            
            # Wild battle, close call → medium uncertainty
            return 0.5
        
        # Exploration summaries — medium uncertainty
        if event_type == 'EXPLORATION_SUMMARY':
            summary = context.get('summary', '')
            if 'rare' in summary.lower() or 'caught' in summary.lower():
                return 0.8
            return 0.3
        
        # Unknown events — medium uncertainty
        return 0.5
    
    def should_invoke_agent(self, event_type: str, context: dict, threshold: float = 0.15) -> bool:
        """
        Determine if agent should be invoked for this event.
        Threshold (default 0.4) can be lowered to invoke more frequently.
        """
        uncertainty = self.score_event_uncertainty(event_type, context)
        return uncertainty >= threshold
    
    def _summarize_event(self, event_type: str, context: dict) -> str:
        """Create a brief summary of a skipped event for batching context"""
        if event_type == 'BATTLE_SUMMARY':
            buffer = context.get('buffer', [])
            for event in buffer:
                if event.get('event') == 'START':
                    return f"Wild battle vs {event.get('enemy', '???')}"
            return "Wild battle"
        elif event_type == 'EXPLORATION_SUMMARY':
            return context.get('summary', 'Explored')
        else:
            return event_type
    
    def _classify_reward(self, action_cmd: str) -> str:
        """
        Classify a GM action command as 'visible', 'ev', or 'none'.
        
        Visible rewards are things the player will actually notice:
          - teachMove → Pokemon has a new move in the menu
          - giveItem → item appears in the bag
          - setShiny → unmissable visual effect
          - setIVs (high) → shows in battle over time
          - addExperience (large) → level up visible
        
        EV-only rewards are invisible in Gen 3 (no EV display).
        """
        if not action_cmd or action_cmd.lower().strip() == 'none':
            return 'none'
        # Invisible rewards
        if any(x in action_cmd for x in ['addEVs', 'setFriendship']):
            return 'ev'
        # Everything else is visible or impactful
        return 'visible'
    
    def _get_pending_arcs(self) -> list:
        """
        Extract pending arc payoffs from PLAYTHROUGH.md.
        Looks for lines with explicit pending markers that Maren has promised.
        Returns up to 5 pending arcs for injection into the agent prompt.
        """
        playthrough = self.memory_dir / 'PLAYTHROUGH.md'
        pending = []
        markers = [
            'IMMEDIATE PAYOFF:',
            'PENDING PAYOFF:',
            'PENDING:',
            'STATUS:',
            'PAYOFF OWED:',
            '→ immediate shiny',
            '→ give it',
            '→ teach',
        ]
        try:
            if playthrough.exists():
                for line in playthrough.read_text().split('\n'):
                    stripped = line.strip()
                    # Skip very short lines and section headers
                    if len(stripped) < 20:
                        continue
                    if any(m.lower() in stripped.lower() for m in markers):
                        # Clean up markdown formatting
                        clean = stripped.lstrip('*- ').rstrip('*')
                        if clean:
                            pending.append(clean)
        except Exception:
            pass
        return pending[:5]
    
    def prompt_agent_async(self, event_type: str, context: dict):
        """Send event to AI agent in background thread (with uncertainty check)"""
        # Always invoke for high-uncertainty events, skip routine ones
        if not self.should_invoke_agent(event_type, context):
            uncertainty = self.score_event_uncertainty(event_type, context)
            C = Colors
            self.log(f"{C.DIM}⏭ Skip (uncertainty {uncertainty:.2f}): {event_type}{C.RESET}")
            # Accumulate skipped event for context in next significant event
            self.skipped_events.append({
                'type': event_type,
                'time': datetime.now().isoformat(),
                'summary': self._summarize_event(event_type, context)
            })
            # Keep max 20 skipped events
            if len(self.skipped_events) > 20:
                self.skipped_events = self.skipped_events[-20:]
            return
        
        if self.agent_busy:
            self.log(f"⏳ Agent busy, queueing: {event_type}")
            self.pending_events.append((event_type, context))
            return
        
        def run_agent():
            self.agent_busy = True
            try:
                prompt = self.build_prompt(event_type, context)
                C = Colors
                self.log(f"{C.MAGENTA}▲ THINKING...{C.RESET}  {C.DIM}{event_type}{C.RESET}")
                
                if self.agent_mode == 'direct':
                    response_text = self._call_anthropic_direct(prompt)
                elif self.agent_mode == 'claude':
                    response_text = self._call_claude_cli(prompt)
                elif self.agent_mode == 'codex':
                    response_text = self._call_codex_cli(prompt)
                else:  # clawdbot (default)
                    response_text = self._call_clawdbot(prompt)
                
                if response_text:
                    C = Colors
                    self.log(f"{C.GREEN}▼ AI RESPONSE{C.RESET}")
                    print(f"  {C.DIM}{'─' * 56}{C.RESET}")
                    
                    # Save to session history if persistent
                    self._add_to_session_history(event_type, prompt, response_text)
                    
                    import re as _re

                    def extract_gm_calls(text):
                        """Extract all clean GM.func(args) calls from a text block."""
                        return _re.findall(r'GM\.\w+\([^)]*\)', text)

                    action_cmds = []  # All GM calls to execute
                    action_cmd = None  # Last ACTION: line (for reward classification)
                    for line in response_text.split('\n')[:15]:
                        if line.strip():
                            if line.startswith('OBSERVATION:'):
                                label = f"{C.CYAN}OBS{C.RESET}"
                                content = line.split(':', 1)[1].strip()
                            elif line.startswith('PATTERN:'):
                                label = f"{C.YELLOW}PTN{C.RESET}"
                                content = line.split(':', 1)[1].strip()
                            elif line.startswith('MEMORY:'):
                                label = f"{C.MAGENTA}MEM{C.RESET}"
                                content = line.split(':', 1)[1].strip()
                            elif line.startswith('ACTION:'):
                                label = f"{C.GREEN}ACT{C.RESET}"
                                content = line.split(':', 1)[1].strip()
                            else:
                                label = f"{C.DIM}...{C.RESET}"
                                content = line.strip()
                            print(f"  {label}  {content}")

                            # Extract ALL GM calls from every line (not just ACTION:)
                            calls = extract_gm_calls(line)
                            action_cmds.extend(calls)
                            if line.strip().startswith('ACTION:'):
                                action_cmd = line.split('ACTION:', 1)[1].strip()

                    print(f"  {C.DIM}{'─' * 56}{C.RESET}")

                    # Classify reward for drought tracking (use first action or action_cmd)
                    classify_target = action_cmds[0] if action_cmds else action_cmd
                    reward_type = self._classify_reward(classify_target)
                    self.reward_history.append(reward_type)
                    if len(self.reward_history) > 10:
                        self.reward_history = self.reward_history[-10:]

                    if reward_type == 'visible':
                        self.ev_drought_count = 0
                        self.session_visible_rewards += 1
                    elif reward_type == 'ev':
                        self.ev_drought_count += 1
                    else:
                        self.ev_drought_count += 1

                    # Execute all extracted GM calls
                    for gm_call in action_cmds:
                        shell_cmd = f"echo '{gm_call}' | nc -w 1 {self.socket_host} {self.socket_port}"
                        readable = self.get_readable_action(gm_call)
                        if reward_type == 'visible':
                            print(f"  {C.BOLD}{C.YELLOW}★ VISIBLE: {readable}{C.RESET}")
                        else:
                            print(f"  {C.BOLD}{C.GREEN}⚡ {readable}{C.RESET}")
                        try:
                            subprocess.run(shell_cmd, shell=True, timeout=5,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                            print(f"  {C.GREEN}✓ {gm_call}{C.RESET}")
                        except subprocess.TimeoutExpired:
                            print(f"  {C.YELLOW}✓ Sent{C.RESET}")

                    if not action_cmds:
                        # No GM calls found — try legacy shell command fallback
                        action_cmd_check = (action_cmd or '').lower().strip()
                        if action_cmd_check and action_cmd_check != 'none':
                            try:
                                action_cmd = action_cmd.replace(' HOST ', f' {self.socket_host} ')
                                action_cmd = action_cmd.replace('nc HOST', f'nc {self.socket_host}')
                                if '| nc ' in action_cmd and ' -w ' not in action_cmd:
                                    action_cmd = action_cmd.replace('| nc ', '| nc -w 1 ')
                                readable = self.get_readable_action(action_cmd)
                                print(f"  {C.BOLD}{C.GREEN}⚡ {readable}{C.RESET}")
                                subprocess.run(action_cmd, shell=True, timeout=5,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                                print(f"  {C.GREEN}✓ Complete{C.RESET}")
                            except subprocess.TimeoutExpired:
                                print(f"  {C.YELLOW}✓ Sent{C.RESET}")
                            except Exception as e:
                                print(f"  {C.RED}✗ Failed: {e}{C.RESET}")
                        else:
                            print(f"  {C.DIM}No action taken (drought: {self.ev_drought_count}){C.RESET}")
                    
            except Exception as e:
                self.log(f"❌ Agent error: {e}")
            finally:
                self.agent_busy = False
                if self.pending_events:
                    next_event, next_ctx = self.pending_events.pop(0)
                    self.prompt_agent_async(next_event, next_ctx)
        
        threading.Thread(target=run_agent, daemon=True).start()
    
    def _call_clawdbot(self, prompt: str) -> str:
        """Call agent via Clawdbot CLI - agent writes response to gm_response.txt"""
        # Clear previous response
        if self.response_file.exists():
            self.response_file.unlink()

        # Inject the absolute output path — AGENTS.md says the daemon provides this
        output_path = str(self.response_file.absolute())
        full_prompt = prompt + f"\n\nOUTPUT: Write your formatted OBS/PTN/MEM/ACT response to this exact file path using your write tool:\n{output_path}"
        
        result = subprocess.run(
            ["clawdbot", "agent", "--agent", self.agent_id,
             "--session-id", self.session_id, "--message", full_prompt],
            capture_output=True, text=True, timeout=120
        )
        
        if result.returncode != 0:
            self.log(f"⚠️ Clawdbot error: {result.stderr[:120]}")
            return ""

        # Check if clawdbot returned the response directly in stdout
        if result.stdout and result.stdout.strip():
            stdout_text = result.stdout.strip()
            # If it looks like a GM response (has OBS/PTN/ACT or GM. calls), use it directly
            if any(x in stdout_text for x in ['OBS', 'PTN', 'ACT', 'GM.', 'MEM']):
                self.response_file.write_text(stdout_text)
                return stdout_text

        # Poll for agent to write response file (up to 90 seconds)
        for _ in range(90):
            time.sleep(1)
            if self.response_file.exists():
                response = self.response_file.read_text().strip()
                if response:
                    return response
        
        self.log("⚠️ Clawdbot: timed out waiting for gm_response.txt")
        return ""
    
    def _call_anthropic_direct(self, prompt: str) -> str:
        """Call Anthropic API directly (no Clawdbot required)"""
        # Add to conversation history
        self.conversation_history.append({"role": "user", "content": prompt})
        
        # Keep history manageable (last 20 turns)
        if len(self.conversation_history) > 40:
            self.conversation_history = self.conversation_history[-40:]
        
        response = self.anthropic_client.messages.create(
            model=self.agent_model,
            max_tokens=1024,
            system=self.system_prompt,
            messages=self.conversation_history
        )
        
        assistant_message = response.content[0].text
        self.conversation_history.append({"role": "assistant", "content": assistant_message})
        
        # Write to response file (for compatibility)
        self.response_file.write_text(assistant_message)
        
        return assistant_message
    
    def _call_claude_cli(self, prompt: str) -> str:
        """Call Claude CLI (uses Claude Code/Max subscription via OAuth)"""
        # Build the full prompt with system context
        full_prompt = f"{self.system_prompt}\n\n---\n\n{prompt}"
        
        result = subprocess.run(
            ["claude", "-p", full_prompt],
            capture_output=True, text=True, timeout=120
        )
        
        if result.returncode == 0:
            response = result.stdout.strip()
            self.response_file.write_text(response)
            return response
        else:
            self.log(f"⚠️ Claude CLI error: {result.stderr[:100]}")
            return ""
    
    def _call_codex_cli(self, prompt: str) -> str:
        """Call Codex CLI (uses OpenAI subscription)"""
        full_prompt = f"{self.system_prompt}\n\n---\n\n{prompt}"
        
        result = subprocess.run(
            ["codex", "-q", full_prompt],
            capture_output=True, text=True, timeout=120
        )
        
        if result.returncode == 0:
            response = result.stdout.strip()
            self.response_file.write_text(response)
            return response
        else:
            self.log(f"⚠️ Codex CLI error: {result.stderr[:100]}")
            return ""
    
    def build_prompt(self, event_type: str, ctx: dict) -> str:
        """Build context-rich prompt for the agent"""
        state = ctx.get('state', {})
        party = state.get('party', [])
        
        # Calculate party health
        if party:
            avg_hp = sum(
                (p.get('current_hp', 0) / max(p.get('max_hp', 1), 1)) * 100
                for p in party
            ) / len(party)
        else:
            avg_hp = 100
        
        session_mins = int((time.time() - self.session_start) / 60)
        
        prompt = f"EVENT: {event_type}\n"
        prompt += f"Party: {self.format_party(party)}\n"
        prompt += f"Party HP: {int(avg_hp)}% avg\n"
        prompt += f"Session: {session_mins} mins | Badges: {state.get('badge_count', 0)}\n"
        prompt += f"Stats: {self.battles_won} wins, {self.pokemon_caught} caught, {self.close_calls} close calls\n"
        prompt += f"Rewards: {self.session_visible_rewards} visible this session | drought={self.ev_drought_count}\n"
        
        # Recent battle history for pattern recognition
        if self.battle_history:
            recent = self.battle_history[-3:]
            history_str = ", ".join([
                f"{b['enemy']}({'close' if b['was_close'] else 'clean'})" 
                for b in recent
            ])
            prompt += f"Recent: {history_str}\n"
        
        # Event-specific details
        if event_type == 'BATTLE_SUMMARY':
            buffer = ctx.get('buffer', [])
            prompt += "=== BATTLE COMPLETE ===\n"
            prompt += "Read the battle text below to determine what happened.\n"
            
            for event in buffer:
                ev = event.get('event', '')
                if ev == 'START':
                    prompt += f"Started: {event.get('type')} battle vs {event.get('enemy')}\n"
                    if event.get('enemy_party'):
                        prompt += f"  Trainer's team: {', '.join(event['enemy_party'])}\n"
                elif ev == 'END':
                    prompt += f"Duration: {event.get('duration_sec', 0)}s, Party HP: {event.get('hp_after', 100)}%\n"
                    if event.get('was_close'):
                        prompt += "⚠️ CLOSE CALL!\n"
                    if event.get('damage_taken'):
                        dmg_str = ", ".join([f"{k}: -{v}HP" for k, v in event['damage_taken'].items()])
                        prompt += f"Damage taken: {dmg_str}\n"
                elif ev == 'CAUGHT':
                    prompt += f"🎉 Caught: {event.get('pokemon')}\n"
            
            battle_dialogue = ctx.get('battle_dialogue', [])
            if battle_dialogue:
                prompt += "\n=== BATTLE TEXT (what the game showed) ===\n"
                for text in battle_dialogue[-30:]:
                    prompt += f"• {text}\n"
            
            # Battle damage log from Lua
            battle_log = ctx.get('battle_log', [])
            if battle_log:
                prompt += "\n=== DAMAGE LOG ===\n"
                for entry in battle_log[-20:]:
                    etype = entry.get('type', '')
                    if etype == 'attack':
                        move_id = entry.get('moveId', 0)
                        move_name = MOVE_NAMES.get(move_id, f"Move#{move_id}")
                        damage = entry.get('damage', 0)
                        enemy_hp = entry.get('enemyHP', '?')
                        enemy_max = entry.get('enemyMaxHP', '?')
                        prompt += f"• {move_name} dealt {damage} damage (enemy: {enemy_hp}/{enemy_max})\n"
                    elif etype == 'damage_taken':
                        damage = entry.get('damage', 0)
                        hp = entry.get('hp', '?')
                        prompt += f"• Took {damage} damage (HP now: {hp})\n"
        
        elif event_type == 'EXPLORATION_SUMMARY':
            state = ctx.get('state', {})
            summary = ctx.get('summary', '')
            
            prompt += f"=== EXPLORATION ===\n{summary}\n"
            
            if state.get('itemsGained', 0) > 0:
                prompt += f"📦 Items gained: {state['itemsGained']}\n"
            if state.get('moneyChange', 0) != 0:
                change = state['moneyChange']
                if change > 0:
                    prompt += f"💰 Money gained: ${change}\n"
                else:
                    prompt += f"💸 Money spent: ${abs(change)}\n"
            if state.get('dialogueCount', 0) > 0:
                prompt += f"💬 NPCs talked to: {state['dialogueCount']}\n"
                # Include actual dialogue text
                dialogues = state.get('dialogueTexts', [])
                for i, text in enumerate(dialogues[:5]):
                    prompt += f"  NPC {i+1}: \"{text[:100]}{'...' if len(text) > 100 else ''}\"\n"
        
        # Add accumulated skipped events as context
        if self.skipped_events:
            prompt += f"\n=== SINCE LAST UPDATE ({len(self.skipped_events)} routine events) ===\n"
            for event in self.skipped_events:
                prompt += f"• {event.get('summary', event.get('type'))}\n"
            prompt += "\n"
            # Clear after including
            self.skipped_events = []
        
        # Add session history context if available
        if self.session_persistent and self.session_history:
            prompt += f"\n=== SESSION HISTORY ({len(self.session_history)} previous events) ===\n"
            # Include last 10 interactions for better continuity
            for entry in self.session_history[-10:]:
                prompt += f"• [{entry.get('event_type', 'unknown')}] {entry.get('response', '')[:200]}\n"
            prompt += "\nYou've seen these events before. Build on this context, don't repeat yourself.\n"
        
        # === MAREN IMPACT SYSTEM ===
        
        # Inject pending arc payoffs (things Maren has promised in PLAYTHROUGH.md)
        pending_arcs = self._get_pending_arcs()
        if pending_arcs:
            prompt += f"\n=== PENDING ARC PAYOFFS (you promised these in PLAYTHROUGH.md) ===\n"
            for arc in pending_arcs:
                prompt += f"• {arc}\n"
            prompt += "\nIf this event creates an opportunity to deliver a payoff, DO IT. Don't defer again.\n"
        
        # Reward drought warning — escalate to visible if Maren has been invisible too long
        if self.ev_drought_count >= 3:
            prompt += f"\n⚠️  IMPACT WARNING: {self.ev_drought_count} consecutive invisible rewards (EVs/none).\n"
            prompt += f"The player hasn't noticed Maren in {self.ev_drought_count} events.\n"
            prompt += "If this event scores 4+ on the checklist, use a VISIBLE reward: teachMove, giveItem, or setShiny.\n"
            prompt += "EVs alone are not enough here. The game needs to feel alive.\n"
        
        # Session reward summary (occasional reminder of what's been given)
        if self.session_visible_rewards == 0 and len(self.reward_history) >= 5:
            prompt += "\n📊 SESSION NOTE: No visible rewards given yet this session. The player hasn't felt Maren.\n"
        
        return prompt
    
    def process_event(self, data: dict):
        """Process event from mGBA"""
        event_type = data.get('event_type', 'unknown')
        self.current_state = data  # Track for helpers
        
        if event_type == 'battle_start':
            enemy = data.get('enemy', {})
            enemy_name = self.get_species_name(enemy.get('species', 0))
            battle_info = data.get('battleInfo', {})
            is_trainer = battle_info.get('is_trainer', False)
            is_double = battle_info.get('is_double', False)
            is_safari = battle_info.get('is_safari', False)
            is_rematch = False
            
            # Check for trainer rematch
            if is_trainer:
                enemy_species = enemy.get('species', 0)
                enemy_level = enemy.get('level', 0)
                is_rematch = self.detect_trainer_rematch(enemy_species, enemy_level)
            
            self.in_battle = True
            self.battle_start_time = time.time()
            
            battle_type = 'TRAINER' if is_trainer else 'WILD'
            if is_double:
                battle_type += ' (DOUBLE)'
            if is_safari:
                battle_type += ' (SAFARI)'
            if is_rematch:
                battle_type += ' (REMATCH)'
            
            self.current_enemy = f"{enemy_name} L{enemy.get('level', '?')}"
            self.battle_buffer = [{
                'event': 'START',
                'type': battle_type,
                'enemy': self.current_enemy,
                'is_double': is_double,
                'is_trainer': is_trainer,
                'is_safari': is_safari,
                'is_rematch': is_rematch
            }]
            
            party = data.get('party', [])
            self.battle_start_hp = {i: p.get('current_hp', 0) for i, p in enumerate(party)}
            self.battle_start_levels = {i: p.get('level', 0) for i, p in enumerate(party)}
            
            C = Colors
            battle_log = f"{C.BOLD}{C.RED}⚔ BATTLE{C.RESET}  {C.YELLOW}{battle_type}{C.RESET} vs {C.WHITE}{C.BOLD}{enemy_name}{C.RESET} L{enemy.get('level', '?')}"
            self.log(battle_log)
            
        elif event_type == 'battle_end':
            outcome = data.get('outcome', 0)
            outcome_name = data.get('outcomeName', 'unknown')
            party = data.get('party', [])
            
            # Check for level ups (indicates win)
            for i, p in enumerate(party):
                if p.get('level', 0) > self.battle_start_levels.get(i, 0):
                    if outcome in [0, 2, 4]:
                        outcome = 1
                        outcome_name = "won"
                        break
            
            # Calculate battle stats
            if party:
                avg_hp = sum(p.get('current_hp', 0) / max(p.get('max_hp', 1), 1) for p in party) / len(party)
            else:
                avg_hp = 1.0
            
            duration = int(time.time() - (self.battle_start_time or time.time()))
            
            # Calculate damage taken during battle
            damage_taken = {}
            for i, p in enumerate(party):
                start_hp = self.battle_start_hp.get(i, p.get('max_hp', 0))
                current_hp = p.get('current_hp', 0)
                if start_hp > current_hp:
                    name = self.get_species_name(p.get('species', 0))
                    damage_taken[name] = start_hp - current_hp
            
            self.battle_buffer.append({
                'event': 'END',
                'outcome': outcome_name,
                'duration_sec': duration,
                'hp_after': int(avg_hp * 100),
                'was_close': avg_hp < 0.25,
                'damage_taken': damage_taken
            })
            
            C = Colors
            if outcome == 1:
                outcome_color = C.GREEN
            elif outcome == 2:
                outcome_color = C.RED
            else:
                outcome_color = C.YELLOW
            self.log(f"{C.BOLD}🏁 END{C.RESET}  {outcome_color}{outcome_name.upper()}{C.RESET}")
            
            if outcome == 1:
                self.battles_won += 1
            if avg_hp < 0.25 and outcome == 1:
                self.close_calls += 1
            
            # Record to battle history
            battle_record = {
                'enemy': getattr(self, 'current_enemy', 'Unknown'),
                'outcome': outcome_name,
                'hp_after': int(avg_hp * 100),
                'was_close': avg_hp < 0.25
            }
            self.battle_history.append(battle_record)
            if len(self.battle_history) > 10:
                self.battle_history.pop(0)
            
            # Debug: show battle dialogue count
            battle_dialogue = data.get('battleDialogue', [])
            battle_log = data.get('battleLog', [])
            C = Colors
            self.log(f"{C.DIM}📜 Battle text: {len(battle_dialogue)} msgs, log: {len(battle_log)} entries{C.RESET}")
            
            # Send to agent
            self.prompt_agent_async('BATTLE_SUMMARY', {
                'state': data,
                'buffer': self.battle_buffer,
                'outcome': outcome_name,
                'battle_dialogue': battle_dialogue,
                'battle_log': battle_log
            })
            
            self.in_battle = False
            self.battle_buffer = []
            
        elif event_type == 'exploration_summary':
            items = data.get('itemsGained', 0)
            money = data.get('moneyChange', 0)
            dialogues = data.get('dialogueCount', 0)
            
            parts = []
            if items > 0:
                parts.append(f"+{items} items")
            if money != 0:
                parts.append(f"${'+' if money > 0 else ''}{money}")
            if dialogues > 0:
                parts.append(f"{dialogues} NPCs")
            
            if parts:
                summary = " │ ".join(parts)
                C = Colors
                self.log(f"{C.BLUE}▸ EXPLORE{C.RESET}  {summary}")
                self.prompt_agent_async('EXPLORATION_SUMMARY', {
                    'state': data,
                    'summary': summary
                })
        
        elif event_type == 'badge_obtained':
            C = Colors
            badge_count = data.get('badgeCount', data.get('badge_count', '?'))
            print(f"\n  {C.BOLD}{C.YELLOW}{'★' * 40}{C.RESET}")
            print(f"  {C.BOLD}{C.YELLOW}★  BADGE OBTAINED!  ★  Total: {badge_count}  ★{C.RESET}")
            print(f"  {C.BOLD}{C.YELLOW}{'★' * 40}{C.RESET}\n")
            self.prompt_agent_async('BADGE_OBTAINED', {'state': data})
        
        elif event_type == 'party_changed':
            # Debounce: only log party every 30 seconds max
            now = time.time()
            if not hasattr(self, '_last_party_log'):
                self._last_party_log = 0
            if now - self._last_party_log < 30:
                return
            self._last_party_log = now
            
            C = Colors
            party = data.get('party', [])
            parts = []
            for p in party:
                name = self.get_species_name(p.get('species', 0))
                level = p.get('level', '?')
                hp = p.get('current_hp', 0)
                max_hp = p.get('max_hp', 1)
                hp_pct = hp / max(max_hp, 1)
                if hp_pct > 0.5:
                    hp_color = C.GREEN
                elif hp_pct > 0.2:
                    hp_color = C.YELLOW
                else:
                    hp_color = C.RED
                parts.append(f"{name} {C.DIM}L{level}{C.RESET} {hp_color}{hp}/{max_hp}{C.RESET}")
            self.log(f"{C.CYAN}▸ PARTY{C.RESET}  {' │ '.join(parts)}")
        
        elif event_type == 'pokemon_caught':
            C = Colors
            species = data.get('species', 0)
            pokemon_name = self.get_species_name(species)
            self.pokemon_caught += 1
            print(f"\n  {C.BOLD}{C.MAGENTA}{'◆' * 30}{C.RESET}")
            print(f"  {C.BOLD}{C.MAGENTA}◆  CAUGHT: {pokemon_name}!  ◆{C.RESET}")
            print(f"  {C.BOLD}{C.MAGENTA}{'◆' * 30}{C.RESET}\n")
            self.prompt_agent_async('POKEMON_CAUGHT', {
                'state': data,
                'caught_species': species
            })
        
        elif event_type == 'move_mastery':
            C = Colors
            move_id = data.get('moveId', 0)
            count = data.get('count', 0)
            move_name = MOVE_NAMES.get(move_id, f"Move #{move_id}")
            self.move_usage[move_id] = count
            self.log(f"{C.YELLOW}★ MASTERY{C.RESET}  {C.WHITE}{C.BOLD}{move_name}{C.RESET} used {count}x")
            self.prompt_agent_async('MOVE_MASTERY', {
                'state': data,
                'move_id': move_id,
                'move_name': move_name,
                'count': count,
            })
        
        elif event_type == 'connected':
            C = Colors
            self.log(f"{C.GREEN}● Ready{C.RESET}  {C.DIM}Game connected{C.RESET}")
    
    def _print_waiting_instructions(self):
        """Print friendly instructions when mGBA isn't connected yet."""
        C = Colors
        print(f"\n  {C.YELLOW}⏳ Waiting for mGBA...{C.RESET}")
        print(f"  {C.DIM}{'─' * 52}{C.RESET}")
        print(f"  {C.CYAN}1.{C.RESET} Open mGBA and load your Pokemon Emerald ROM")
        print(f"  {C.CYAN}2.{C.RESET} Tools → Scripting → click {C.BOLD}\"Script...\"{C.RESET}")
        print(f"  {C.CYAN}3.{C.RESET} Select: {C.BOLD}lua/game_master_v2.lua{C.RESET}")
        print(f"  {C.CYAN}4.{C.RESET} Scripting console should show:")
        print(f"     {C.DIM}[GM] Listening on {self.socket_host}:{self.socket_port}{C.RESET}")

        if _is_wsl() and self.socket_host == '127.0.0.1':
            win_ip = _get_windows_ip()
            print(f"\n  {C.YELLOW}  WSL detected:{C.RESET} If mGBA is on Windows, use the Windows IP:")
            if win_ip:
                print(f"  {C.YELLOW}  → Set emulator.host: \"{win_ip}\" in config.yaml{C.RESET}")
            else:
                print(f"  {C.YELLOW}  → Run ipconfig on Windows → find 'vEthernet (WSL)' IP{C.RESET}")
            print(f"  {C.YELLOW}  → See README: WSL Setup section{C.RESET}")

        print(f"\n  {C.DIM}Tip: Run with --check to validate your full setup first{C.RESET}")
        print(f"  {C.DIM}Retrying every 5 seconds...{C.RESET}\n")

    def run(self):
        """Main event loop"""
        self.print_banner()

        _waiting_shown = False
        while True:
            if not self.connected:
                if not self.connect():
                    if not _waiting_shown:
                        self._print_waiting_instructions()
                        _waiting_shown = True
                    time.sleep(5)
                    continue
                _waiting_shown = False  # Reset on successful connect
            
            try:
                ready = select.select([self.sock], [], [], 0.1)
                if ready[0]:
                    data = self.sock.recv(16384).decode()
                    for line in data.strip().split('\n'):
                        if line:
                            try:
                                self.process_event(json.loads(line))
                            except json.JSONDecodeError:
                                pass
            except (BlockingIOError, ConnectionResetError):
                if isinstance(sys.exc_info()[1], ConnectionResetError):
                    self.log("❌ Connection lost, reconnecting...")
                    self.connected = False
                    time.sleep(2)
            except KeyboardInterrupt:
                self.log("👋 Shutting down")
                break
            except Exception as e:
                self.log(f"❌ Error: {e}")
                self.connected = False
                time.sleep(2)


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Emerald Daemon — AI Game Master for Pokemon Emerald",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 daemon/agentic_emerald.py             # Start the daemon
  python3 daemon/agentic_emerald.py --check     # Validate setup without starting
  python3 daemon/agentic_emerald.py -c /path/to/config.yaml  # Custom config
        """
    )
    parser.add_argument('-c', '--config', default='config.yaml',
                        help='Path to config file (default: config.yaml)')
    parser.add_argument('--check', action='store_true',
                        help='Validate setup (config, mGBA connection, agent) without starting')
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path

    if args.check:
        check_setup(config_path)
        return

    config = load_config(config_path)
    base_path = config_path.parent

    gm = PokemonGM(config, base_path)
    gm.run()


if __name__ == "__main__":
    main()
