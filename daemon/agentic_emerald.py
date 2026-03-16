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


class LearningDirectives:
    """
    Issue #23 — Controllable Learning Focus ("Tell Me What To Learn", arxiv 2602.23201).

    Allows configuration of what patterns Maren should prioritize learning from.
    Instead of treating all gameplay signals equally, the user can specify
    natural language directives that guide Maren's attention.

    Example directives:
        - "Track momentum shifts — when player goes from losing streak to winning"
        - "Notice Pokemon that get benched and brought back — loyalty under pressure"
        - "Pay attention to type specialization — are they becoming a Fire trainer?"

    Directives are injected into every Maren prompt as structured guidance,
    making her observations more intentional and personalized.
    """

    DEFAULT_DIRECTIVES = [
        "Track ace Pokemon — who leads most battles? Who closes them?",
        "Notice comeback patterns — wins after losses show resilience",
        "Watch for type specialization — is a trainer identity forming?",
        "Observe loyalty signals — benched Pokemon brought back under pressure",
    ]

    def __init__(self, directives: list = None):
        self.directives = directives if directives else self.DEFAULT_DIRECTIVES

    def get_context_block(self) -> str:
        """Format directives as a prompt block for injection."""
        if not self.directives:
            return ''

        lines = ['=== LEARNING FOCUS (what to pay attention to) ===']
        for i, directive in enumerate(self.directives[:6], 1):  # Max 6 directives
            lines.append(f"{i}. {directive}")
        lines.append('')
        lines.append('When observing events, prioritize patterns that match these directives.')
        lines.append('Let these guide what you notice, remember, and reward.')
        lines.append('=== END LEARNING FOCUS ===')
        return '\n'.join(lines)


class PlayerProfileTracker:
    """
    Issue #19 — Explicit Player Attribute Profiling (EXACT-inspired, arxiv 2602.17695).

    Tracks observable behavior signals from gameplay and distills them into explicit
    player attributes injected into every Maren prompt for inference-time personalization.

    Unlike training-time personalization, this is purely behavioral: profile updates
    as the player plays, requiring zero extra configuration or fine-tuning.

    Attributes tracked:
        ace_pokemon         — which Pokemon is trusted most (battles led)
        pokemon_trust       — per-species battle record
        move_mastery        — move usage counts (signature move detection)
        playstyle           — grinder | speedrunner | balanced | completionist
        risk_tolerance      — close call rate (0 = cautious, 1 = reckless)
        ace_consistency     — how loyal they are to one lead
        type_specialization — dominant type if 40%+ exposure skews one way
        comeback_ratio      — how often they win after a loss
    """

    PROFILE_VERSION = 2

    def __init__(self, profile_path: Path, species_names: dict):
        self.path = profile_path
        self.species_names = species_names
        self.profile = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.load(open(self.path))
                if data.get('version') == self.PROFILE_VERSION:
                    return data
            except Exception:
                pass
        return self._default()

    def _default(self) -> dict:
        return {
            'version': self.PROFILE_VERSION,
            'updated_at': datetime.now().isoformat(),
            # Per-Pokemon trust: {str(species_id): {"name", "battles_led", "battles_won"}}
            'pokemon_trust': {},
            # Type exposure: {type_name: battle_count}
            'type_exposure': {},
            # Move mastery: {str(move_id): {"name", "count"}}
            'move_mastery': {},
            # Career totals
            'total_battles': 0,
            'battles_won': 0,
            'battles_lost': 0,
            'close_calls': 0,
            'pokemon_caught': 0,
            # Last-loss flag for comeback tracking
            '_last_was_loss': False,
            'comebacks': 0,     # wins immediately after a loss
            # Derived attributes (recomputed on each save)
            'attributes': {
                'playstyle': 'unknown',
                'risk_tolerance': 0.5,
                'ace_consistency': 0.5,
                'type_specialization': None,
                'comeback_ratio': 0.5,
            }
        }

    def _save(self):
        self._recompute_attributes()
        self.profile['updated_at'] = datetime.now().isoformat()
        try:
            with open(self.path, 'w') as f:
                json.dump(self.profile, f, indent=2)
        except Exception:
            pass

    def _recompute_attributes(self):
        p = self.profile
        attrs = p['attributes']
        battles = p['total_battles']

        # Risk tolerance — how often does the player end up in a close call?
        if battles > 0:
            attrs['risk_tolerance'] = round(p['close_calls'] / battles, 2)

        # Ace consistency — what fraction of battles does the top trusted Pokemon lead?
        trust = p['pokemon_trust']
        if trust and battles > 5:
            max_led = max(v['battles_led'] for v in trust.values())
            attrs['ace_consistency'] = round(max_led / battles, 2)

        # Comeback ratio
        if p['battles_won'] > 0:
            attrs['comeback_ratio'] = round(p['comebacks'] / p['battles_won'], 2)

        # Playstyle inferred from battle density vs catch rate
        if battles > 20:
            catch_rate = p['pokemon_caught'] / battles
            close_rate = p['close_calls'] / battles
            if catch_rate > 0.15:
                attrs['playstyle'] = 'completionist'
            elif close_rate > 0.35:
                attrs['playstyle'] = 'aggressive'
            elif close_rate < 0.08:
                attrs['playstyle'] = 'careful'
            else:
                attrs['playstyle'] = 'balanced'

        # Type specialization — any type > 40% of exposure?
        exposure = p['type_exposure']
        if exposure:
            total = sum(exposure.values())
            top_type = max(exposure, key=exposure.get)
            if total > 0 and exposure[top_type] / total > 0.40:
                attrs['type_specialization'] = top_type
            else:
                attrs['type_specialization'] = None

    def update_battle(self, outcome: str, party: list, was_close: bool, is_trainer: bool):
        """Update profile from battle end event."""
        p = self.profile
        p['total_battles'] += 1

        won = (outcome == 'won')
        lost = (outcome == 'lost')

        if won:
            p['battles_won'] += 1
            if p.get('_last_was_loss'):
                p['comebacks'] += 1
        elif lost:
            p['battles_lost'] += 1

        p['_last_was_loss'] = lost
        if was_close:
            p['close_calls'] += 1

        # Track lead Pokemon (slot 0)
        if party:
            lead = party[0]
            species_id = str(lead.get('species', 0))
            name = self.species_names.get(int(species_id), f"Pokemon #{species_id}")
            rec = p['pokemon_trust'].setdefault(species_id, {
                'name': name, 'battles_led': 0, 'battles_won': 0
            })
            rec['battles_led'] += 1
            if won:
                rec['battles_won'] += 1

        self._save()

    def update_caught(self, species_id: int, species_name: str):
        """Update profile when a Pokemon is caught."""
        self.profile['pokemon_caught'] += 1
        self._save()

    def update_move_mastery(self, move_id: int, count: int, move_name: str):
        """Update profile on move mastery milestone."""
        self.profile['move_mastery'][str(move_id)] = {'name': move_name, 'count': count}
        self._save()

    def get_context_block(self) -> str:
        """Format player profile as a structured context block for prompt injection."""
        p = self.profile
        attrs = p['attributes']
        trust = p['pokemon_trust']

        if p['total_battles'] < 3:
            return ''   # Not enough data yet — don't inject noise

        lines = ['=== PLAYER PROFILE ===']

        # Ace Pokemon
        if trust:
            sorted_trust = sorted(trust.items(), key=lambda x: x[1]['battles_led'], reverse=True)
            ace_id, ace_data = sorted_trust[0]
            ace_name = ace_data['name']
            ace_led = ace_data['battles_led']
            ace_won = ace_data.get('battles_won', 0)
            lines.append(f"Ace: {ace_name} — led {ace_led} battles, won {ace_won}")
            if len(sorted_trust) > 1:
                bench = ', '.join(f"{d['name']} ({d['battles_led']})"
                                  for _, d in sorted_trust[1:4])
                lines.append(f"Trusted partners: {bench}")

        # Playstyle + risk
        playstyle = attrs.get('playstyle', 'unknown')
        risk = attrs.get('risk_tolerance', 0.5)
        if playstyle != 'unknown':
            lines.append(f"Playstyle: {playstyle}")
        if risk > 0.35:
            lines.append(f"Risk: high (close calls in {int(risk*100)}% of battles)")
        elif risk < 0.08:
            lines.append(f"Risk: very cautious (rarely in danger)")

        # Comeback
        comeback = attrs.get('comeback_ratio', 0)
        if p['comebacks'] >= 2:
            lines.append(f"Comeback player: yes ({p['comebacks']} wins after losses)")

        # Ace loyalty
        ace_cons = attrs.get('ace_consistency', 0)
        if ace_cons > 0.70:
            lines.append(f"Ace loyalty: very high ({int(ace_cons*100)}% battles led by ace)")

        # Type identity
        type_spec = attrs.get('type_specialization')
        if type_spec:
            lines.append(f"Type identity: {type_spec} trainer")

        # Signature move
        mastery = p.get('move_mastery', {})
        if mastery:
            top_move = max(mastery.values(), key=lambda x: x['count'])
            lines.append(f"Signature move: {top_move['name']} (used {top_move['count']}x)")

        lines.append(f"Career: {p['total_battles']} battles | {p['pokemon_caught']} caught | {p['close_calls']} clutch moments")
        lines.append('=== END PLAYER PROFILE ===')
        return '\n'.join(lines)


class DecisionLogger:
    """
    Issue #20 — Maren Decision Library (MAS-on-the-Fly-inspired, arxiv 2602.13671).

    Phase 1 (current): Data collection only.
    Logs every reward decision to decisions.jsonl so patterns can emerge over sessions.

    Phase 2 (future, after 10+ sessions): Retrieve similar past decisions via event_type
    matching and inject as 'what worked before' context — exactly MAS-on-the-Fly's
    retrieval-augmented SOP instantiation applied to narrative reward decisions.

    Log schema:
        ts, event_type, action, reward_type, drought, arcs_active,
        session_visible, arc_closed, response_snippet
    """

    MIN_ENTRIES_FOR_RETRIEVAL = 20  # Don't retrieve until we have enough data

    def __init__(self, log_path: Path):
        self.path = log_path

    def log(self, event_type: str, action_cmd: str, reward_type: str,
            drought: int, arcs_active: int, session_visible: int,
            arc_closed: str = None, response_snippet: str = ''):
        """Append a decision record."""
        entry = {
            'ts': datetime.now().isoformat(),
            'event_type': event_type,
            'action': action_cmd or 'none',
            'reward_type': reward_type,
            'drought': drought,
            'arcs_active': arcs_active,
            'session_visible': session_visible,
            'arc_closed': arc_closed,
            'snippet': response_snippet[:200] if response_snippet else '',
        }
        try:
            with open(self.path, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception:
            pass

    def get_recent_patterns(self, event_type: str, n: int = 3) -> str:
        """
        Phase 2 retrieval: fetch recent successful decisions for the same event type.
        Returns empty string until MIN_ENTRIES_FOR_RETRIEVAL decisions are logged.
        """
        try:
            if not self.path.exists():
                return ''
            entries = []
            with open(self.path) as f:
                for line in f:
                    try:
                        entries.append(json.loads(line.strip()))
                    except Exception:
                        pass

            if len(entries) < self.MIN_ENTRIES_FOR_RETRIEVAL:
                return ''   # Not enough data yet

            # Filter to visible rewards for the same event type (the "successes")
            relevant = [e for e in entries
                        if e['reward_type'] == 'visible' and e['event_type'] == event_type]
            if not relevant:
                return ''

            recent = relevant[-n:]
            lines = ['=== PAST SUCCESSFUL DECISIONS (similar events) ===']
            for e in recent:
                arc_note = f" [closed {e['arc_closed']}]" if e.get('arc_closed') else ''
                lines.append(f"• {e['event_type']} → {e['action']}{arc_note}")
            lines.append('Consider what made these work and whether the current moment is similar.')
            lines.append('=== END PAST DECISIONS ===')
            return '\n'.join(lines)
        except Exception:
            return ''


class TrajectoryLearner:
    """
    Issue #37 — Trajectory Learning System (IBM arxiv 2603.10600-inspired).

    Analyzes decisions.jsonl to extract strategic insights that guide future decisions.
    Based on "Trajectory-Informed Memory Generation for Self-Improving Agent Systems":
    - Trajectory Intelligence Extractor: parses decision logs
    - Contextual Learning Generator: produces strategy/recovery/optimization tips
    - Adaptive Memory Retrieval: injects learned strategies into prompts

    Output: structured "LEARNED STRATEGIES" block injected after player profile.
    Only activates after MIN_ENTRIES decisions are logged.
    """

    MIN_ENTRIES = 30  # Need enough data for meaningful patterns
    CACHE_TTL_SEC = 3600  # Re-analyze every hour (not every prompt)

    def __init__(self, decisions_path: Path):
        self.decisions_path = decisions_path
        self._cache = None
        self._cache_time = 0

    def analyze(self) -> dict:
        """
        Extract strategic patterns from decisions.jsonl.
        Returns dict with: event_patterns, drought_recovery, strategy_tips.
        """
        if not self.decisions_path.exists():
            return {}

        try:
            entries = []
            with open(self.decisions_path) as f:
                for line in f:
                    try:
                        entries.append(json.loads(line.strip()))
                    except Exception:
                        pass

            if len(entries) < self.MIN_ENTRIES:
                return {}

            # --- Trajectory Intelligence Extraction ---

            # 1. Event type effectiveness (none rate per type)
            event_stats = {}
            for e in entries:
                etype = e.get('event_type', 'unknown')
                rtype = e.get('reward_type', 'none')
                if etype not in event_stats:
                    event_stats[etype] = {'total': 0, 'visible': 0, 'ev': 0, 'none': 0}
                event_stats[etype]['total'] += 1
                event_stats[etype][rtype] = event_stats[etype].get(rtype, 0) + 1

            # 2. Drought recovery patterns (what actions broke high droughts)
            drought_breaks = []  # entries where drought was high and visible reward given
            for e in entries:
                if e.get('reward_type') == 'visible' and e.get('drought', 0) >= 5:
                    drought_breaks.append({
                        'drought': e['drought'],
                        'event_type': e['event_type'],
                        'action': e['action'],
                    })

            # 3. Average drought at visible reward
            visible_droughts = [e.get('drought', 0) for e in entries if e.get('reward_type') == 'visible']
            avg_drought_at_visible = sum(visible_droughts) / len(visible_droughts) if visible_droughts else 0

            # 4. Arc closure success rate (when arcs are closed)
            arc_closures = [e for e in entries if e.get('arc_closed')]

            return {
                'event_stats': event_stats,
                'drought_breaks': drought_breaks,
                'avg_drought_at_visible': avg_drought_at_visible,
                'arc_closures': arc_closures,
                'total_entries': len(entries),
            }

        except Exception:
            return {}

    def get_strategies_block(self, current_event_type: str = None) -> str:
        """
        Generate "LEARNED STRATEGIES" block for prompt injection.
        Caches analysis to avoid re-reading on every prompt.
        """
        now = time.time()
        if self._cache is None or (now - self._cache_time) > self.CACHE_TTL_SEC:
            self._cache = self.analyze()
            self._cache_time = now

        analysis = self._cache
        if not analysis:
            return ''

        tips = []
        event_stats = analysis.get('event_stats', {})
        drought_breaks = analysis.get('drought_breaks', [])
        avg_drought = analysis.get('avg_drought_at_visible', 0)
        arc_closures = analysis.get('arc_closures', [])

        # --- Contextual Learning Generator ---

        # Strategy tip: identify underused event types
        underused = []
        for etype, stats in event_stats.items():
            if stats['total'] >= 5:
                none_rate = stats['none'] / stats['total']
                if none_rate > 0.95:
                    underused.append((etype, int(none_rate * 100)))

        if underused:
            worst = max(underused, key=lambda x: x[1])
            tips.append(f"📊 UNDERUSED: {worst[0]} has {worst[1]}% none rate — these events are opportunities")

        # Recovery tip: what breaks droughts
        if drought_breaks:
            # Group by action pattern
            actions = {}
            for db in drought_breaks:
                action = db['action'].split('(')[0] if '(' in db['action'] else db['action']
                actions[action] = actions.get(action, 0) + 1
            top_action = max(actions.items(), key=lambda x: x[1])
            tips.append(f"🔧 RECOVERY: {top_action[0]} broke drought {top_action[1]}x in past sessions")

        # Optimization tip: when to act
        if avg_drought > 0:
            tips.append(f"⏱️ TIMING: Visible rewards typically come at drought {avg_drought:.1f} — consider acting earlier")

        # Arc tip: what works for arc closure
        if arc_closures:
            tips.append(f"🎯 ARCS: {len(arc_closures)} arc closures successful — explicit payoffs work")

        # Current event context
        if current_event_type and current_event_type in event_stats:
            stats = event_stats[current_event_type]
            if stats['total'] >= 3:
                visible_rate = stats['visible'] / stats['total'] * 100
                if visible_rate < 15:
                    tips.append(f"🎲 THIS EVENT: {current_event_type} only gets visible rewards {visible_rate:.0f}% of the time — break the pattern")

        if not tips:
            return ''

        lines = ['=== LEARNED STRATEGIES (from your past decisions) ===']
        lines.extend(tips)
        lines.append('Use these insights. They come from what actually worked before.')
        lines.append('=== END LEARNED STRATEGIES ===')
        return '\n'.join(lines)


class SkillExtractor:
    """
    Issue #38 — Skill Extraction from Decision Trajectories (XSkill-inspired, arxiv 2603.12056).

    XSkill proposes dual-stream learning:
    - Experiences: action-level guidance (raw decisions — already have via DecisionLogger)
    - Skills: task-level patterns that generalize across situations

    This class extracts reusable "skills" from successful decisions:
    - Identifies repeating patterns (e.g., "ace sweep → Fire item reward")
    - Abstracts to transferable procedures
    - Matches current context to applicable skills

    Key insight from XSkill: +33% improvement on tool use from skill extraction.
    Skills are more reusable than raw experiences because they abstract the context.

    Output: "APPLICABLE SKILLS" block with relevant procedural patterns.
    """

    MIN_ENTRIES = 20  # Need enough decisions to extract patterns
    CACHE_TTL_SEC = 3600  # Re-extract skills hourly (expensive operation)

    def __init__(self, decisions_path: Path):
        self.decisions_path = decisions_path
        self._skills_cache = None
        self._cache_time = 0

    def _extract_context_signals(self, snippet: str) -> dict:
        """
        Parse the response snippet to extract context signals for skill matching.
        Returns dict with: pokemon_mentioned, action_context, emotional_tone.
        """
        signals = {
            'pokemon': [],
            'action_context': [],  # sweep, clutch, close_call, rematch, etc.
            'emotional': [],  # resilience, dominance, underdog, etc.
        }

        snippet_lower = snippet.lower()

        # Pokemon detection (common starters and team members)
        pokemon_names = ['blaziken', 'combusken', 'torchic', 'swellow', 'ninjask',
                         'slaking', 'kirlia', 'ralts', 'lombre', 'pelipper']
        for poke in pokemon_names:
            if poke in snippet_lower:
                signals['pokemon'].append(poke.capitalize())

        # Action context detection
        if any(w in snippet_lower for w in ['sweep', 'swept', 'clean', 'one turn', 'no damage']):
            signals['action_context'].append('sweep')
        if any(w in snippet_lower for w in ['clutch', 'close', 'close call', 'close-call']):
            signals['action_context'].append('clutch')
        if any(w in snippet_lower for w in ['rematch', 're-match', 'revenge']):
            signals['action_context'].append('rematch')
        if any(w in snippet_lower for w in ['crit', 'critical']):
            signals['action_context'].append('crit')
        if any(w in snippet_lower for w in ['level', 'leveled', 'evolved', 'evolution']):
            signals['action_context'].append('milestone')

        # Emotional tone detection
        if any(w in snippet_lower for w in ['tanked', 'pushed through', 'despite']):
            signals['emotional'].append('resilience')
        if any(w in snippet_lower for w in ['dominated', 'swept', 'clean']):
            signals['emotional'].append('dominance')
        if any(w in snippet_lower for w in ['underdog', 'type disadvantage', 'against odds']):
            signals['emotional'].append('underdog')

        return signals

    def _cluster_successful_decisions(self, entries: list) -> list:
        """
        Group successful (visible reward) decisions by similar context.
        Returns clusters of decisions that share context patterns.
        """
        visible = [e for e in entries if e.get('reward_type') == 'visible']
        if len(visible) < 3:
            return []

        # Extract context signals for each visible decision
        enriched = []
        for e in visible:
            signals = self._extract_context_signals(e.get('snippet', ''))
            enriched.append({
                **e,
                'signals': signals,
            })

        # Group by action pattern (the GM command function)
        action_groups = {}
        for e in enriched:
            action = e.get('action', 'none')
            # Extract just the function name
            if '(' in action:
                func = action.split('(')[0].replace('GM.', '')
            else:
                func = action
            if func not in action_groups:
                action_groups[func] = []
            action_groups[func].append(e)

        # For each action group with 2+ entries, look for context patterns
        clusters = []
        for func, group in action_groups.items():
            if len(group) < 2:
                continue

            # Find common context signals
            all_pokemon = []
            all_contexts = []
            all_emotional = []
            for e in group:
                all_pokemon.extend(e['signals']['pokemon'])
                all_contexts.extend(e['signals']['action_context'])
                all_emotional.extend(e['signals']['emotional'])

            # Count frequencies
            from collections import Counter
            pokemon_freq = Counter(all_pokemon)
            context_freq = Counter(all_contexts)
            emotional_freq = Counter(all_emotional)

            # Extract common patterns (appearing in 50%+ of decisions)
            threshold = len(group) / 2
            common_pokemon = [p for p, c in pokemon_freq.items() if c >= threshold]
            common_context = [c for c, cnt in context_freq.items() if cnt >= threshold]
            common_emotional = [e for e, cnt in emotional_freq.items() if cnt >= threshold]

            if common_pokemon or common_context or common_emotional:
                clusters.append({
                    'action': func,
                    'count': len(group),
                    'common_pokemon': common_pokemon,
                    'common_context': common_context,
                    'common_emotional': common_emotional,
                    'example_snippet': group[-1].get('snippet', '')[:100],
                })

        return clusters

    def _generate_skills(self, clusters: list) -> list:
        """
        Convert context clusters into reusable procedural "skills".
        Each skill is a natural-language pattern that can be applied.
        """
        skills = []

        for cluster in clusters:
            action = cluster['action']
            count = cluster['count']
            pokemon = cluster.get('common_pokemon', [])
            context = cluster.get('common_context', [])
            emotional = cluster.get('common_emotional', [])

            # Generate skill description based on patterns
            conditions = []
            if pokemon:
                conditions.append(f"when {'/'.join(pokemon)} is involved")
            if 'sweep' in context:
                conditions.append("after a clean sweep")
            if 'clutch' in context:
                conditions.append("after a clutch battle")
            if 'milestone' in context:
                conditions.append("on a level/evolution milestone")
            if 'dominance' in emotional:
                conditions.append("to reinforce dominance")
            if 'resilience' in emotional:
                conditions.append("to acknowledge resilience")

            if not conditions:
                conditions = ["in similar situations"]

            # Map action to readable reward type
            action_readable = {
                'give': 'Give item from bag',
                'giveItem': 'Equip held item',
                'teachMove': 'Teach a new move',
                'addExperience': 'Award bonus XP',
                'setShiny': 'Make shiny',
                'setFriendship': 'Max friendship',
            }.get(action, f'Use GM.{action}')

            skill = {
                'pattern': ' + '.join(conditions[:2]),  # Limit to 2 conditions
                'action': action_readable,
                'confidence': count,  # How many times this pattern succeeded
                'raw_action': action,
            }
            skills.append(skill)

        # Sort by confidence (most reliable patterns first)
        skills.sort(key=lambda x: -x['confidence'])
        return skills[:5]  # Return top 5 skills

    def extract_skills(self) -> list:
        """
        Main extraction method. Returns list of skill dicts.
        Caches results for CACHE_TTL_SEC.
        """
        now = time.time()
        if self._skills_cache is not None and (now - self._cache_time) < self.CACHE_TTL_SEC:
            return self._skills_cache

        if not self.decisions_path.exists():
            return []

        try:
            entries = []
            with open(self.decisions_path) as f:
                for line in f:
                    try:
                        entries.append(json.loads(line.strip()))
                    except Exception:
                        pass

            if len(entries) < self.MIN_ENTRIES:
                return []

            clusters = self._cluster_successful_decisions(entries)
            skills = self._generate_skills(clusters)

            self._skills_cache = skills
            self._cache_time = now
            return skills

        except Exception:
            return []

    def get_applicable_skills(self, event_type: str, context_snippet: str = '') -> str:
        """
        Return skills block for prompt injection.
        Filters to skills relevant to current context.
        """
        skills = self.extract_skills()
        if not skills:
            return ''

        # Extract signals from current context
        current_signals = self._extract_context_signals(context_snippet)

        # Score skills by relevance to current context
        scored_skills = []
        for skill in skills:
            score = skill['confidence']  # Base score

            # Boost if pokemon matches current context
            pattern_lower = skill['pattern'].lower()
            for poke in current_signals['pokemon']:
                if poke.lower() in pattern_lower:
                    score += 2

            # Boost if action context matches
            for ctx in current_signals['action_context']:
                if ctx in pattern_lower:
                    score += 1

            scored_skills.append((skill, score))

        # Sort by relevance score
        scored_skills.sort(key=lambda x: -x[1])

        # Take top 3 relevant skills
        relevant = [s[0] for s in scored_skills[:3]]

        if not relevant:
            return ''

        lines = ['=== APPLICABLE SKILLS (patterns that worked before) ===']
        for skill in relevant:
            conf_indicator = '★' * min(skill['confidence'], 3)  # Up to 3 stars
            lines.append(f"{conf_indicator} {skill['pattern']} → {skill['action']}")
        lines.append('These are abstracted patterns from successful past decisions.')
        lines.append('=== END APPLICABLE SKILLS ===')
        return '\n'.join(lines)


class ArcGenerator:
    """
    Issue #40 — Auto-Arc Generation (Story Hook Detection).
    
    When the ARC LEDGER is nearly empty (no HIGH priority PENDING arcs),
    Maren has nothing to work toward. This class detects arc opportunities
    from the current team state and generates new story hooks.
    
    Research alignment: This addresses the root cause of the 91% "none" rate.
    If Maren has no goals, she defaults to passivity. By generating arcs
    dynamically, we give her narrative purpose.
    
    Arc detection heuristics:
    - Pokemon approaching evolution → "Evolution Watch" arc
    - Pokemon leading 3+ consecutive battles → "MVP Recognition" arc
    - Pokemon with low move coverage → "Move Upgrade" arc
    - Recently caught Pokemon → "Proving Ground" arc
    - Type coverage gaps → "Team Balance" arc
    
    Arcs are auto-added to PLAYTHROUGH.md when inventory is low.
    """
    
    # Evolution level thresholds for common Pokemon (species_id -> evolution_level)
    # Gen 3 starters and common mons
    EVOLUTION_LEVELS = {
        1: 16,    # Bulbasaur → Ivysaur
        4: 16,    # Charmander → Charmeleon
        7: 16,    # Squirtle → Wartortle
        152: 16,  # Chikorita → Bayleef
        155: 14,  # Cyndaquil → Quilava
        158: 18,  # Totodile → Croconaw
        252: 16,  # Treecko → Grovyle
        255: 16,  # Torchic → Combusken
        258: 16,  # Mudkip → Marshtomp
        261: 18,  # Poochyena → Mightyena
        263: 20,  # Zigzagoon → Linoone
        265: 7,   # Wurmple → Silcoon/Cascoon
        270: 14,  # Lotad → Lombre
        273: 14,  # Seedot → Nuzleaf
        276: 22,  # Taillow → Swellow
        278: 25,  # Wingull → Pelipper
        280: 20,  # Ralts → Kirlia
        283: 22,  # Surskit → Masquerain
        285: 23,  # Shroomish → Breloom
        287: 18,  # Slakoth → Vigoroth
        290: 20,  # Nincada → Ninjask
        293: 20,  # Whismur → Loudred
        296: 24,  # Makuhita → Hariyama
        304: 32,  # Aron → Lairon
        307: 37,  # Meditite → Medicham
        309: 26,  # Electrike → Manectric
        318: 30,  # Carvanha → Sharpedo
        320: 40,  # Wailmer → Wailord
        322: 33,  # Numel → Camerupt
        325: 32,  # Spoink → Grumpig
        328: 35,  # Trapinch → Vibrava
        331: 32,  # Cacnea → Cacturne
        333: 35,  # Swablu → Altaria
        339: 30,  # Barboach → Whiscash
        341: 30,  # Corphish → Crawdaunt
        343: 36,  # Baltoy → Claydol
        345: 40,  # Lileep → Cradily
        347: 40,  # Anorith → Armaldo
        349: 20,  # Feebas → Milotic (beauty)
        353: 37,  # Shuppet → Banette
        355: 37,  # Duskull → Dusclops
        361: 42,  # Snorunt → Glalie
        363: 32,  # Spheal → Sealeo
        366: 1,   # Clamperl → trade evos
        371: 30,  # Bagon → Shelgon
        374: 20,  # Beldum → Metang
    }
    
    # Second stage evolution levels
    EVOLUTION_LEVELS_STAGE2 = {
        2: 32,    # Ivysaur → Venusaur
        5: 36,    # Charmeleon → Charizard
        8: 36,    # Wartortle → Blastoise
        153: 32,  # Bayleef → Meganium
        156: 36,  # Quilava → Typhlosion
        159: 30,  # Croconaw → Feraligatr
        253: 36,  # Grovyle → Sceptile
        256: 36,  # Combusken → Blaziken
        259: 36,  # Marshtomp → Swampert
        281: 30,  # Kirlia → Gardevoir
        288: 36,  # Vigoroth → Slaking
        294: 40,  # Loudred → Exploud
        305: 42,  # Lairon → Aggron
        329: 45,  # Vibrava → Flygon
        364: 44,  # Sealeo → Walrein
        372: 50,  # Shelgon → Salamence
        375: 45,  # Metang → Metagross
    }
    
    # Strong moves worth suggesting (move_id -> move_name)
    STRONG_MOVES = {
        53: "Flamethrower",
        58: "Ice Beam",
        85: "Thunderbolt",
        89: "Earthquake",
        94: "Psychic",
        188: "Sludge Bomb",
        202: "Giga Drain",
        231: "Iron Tail",
        237: "Hidden Power",
        247: "Shadow Ball",
        257: "Heat Wave",
        299: "Blaze Kick",
        332: "Aerial Ace",
        352: "Water Pulse",
    }
    
    # Gen 3 commonly useful held items
    HELD_ITEMS = {
        234: "Leftovers",
        253: "Shell Bell",
        232: "Scope Lens",
        217: "Quick Claw",
        221: "King's Rock",
        219: "Bright Powder",
        230: "Focus Band",
        215: "Charcoal",
        220: "Mystic Water",
        227: "Soft Sand",
        223: "NeverMeltIce",
        216: "Magnet",
        237: "BlackGlasses",
    }
    
    MIN_HIGH_ARCS = 1  # Minimum HIGH priority arcs to maintain
    
    def __init__(self, playthrough_path: Path, species_names: dict):
        self.playthrough_path = playthrough_path
        self.species_names = species_names
        self.last_generation_time = 0
        self.GENERATION_COOLDOWN = 3600  # 1 hour cooldown between generations
    
    def needs_new_arcs(self, pending_arcs: list) -> bool:
        """
        Check if we need to generate new arcs.
        
        Returns True if:
        - No PENDING arcs at all, OR
        - No HIGH priority PENDING arcs
        """
        if not pending_arcs:
            return True
        
        high_pending = [a for a in pending_arcs if a.get('priority') == 'HIGH' and a.get('status') in ('PENDING', 'IMMEDIATE')]
        return len(high_pending) < self.MIN_HIGH_ARCS
    
    def generate_arcs(self, party: list, player_profile: dict, battle_history: list) -> list:
        """
        Generate new arc suggestions based on current team state.
        
        Args:
            party: Current party from game state
            player_profile: From PlayerProfileTracker
            battle_history: Recent battle records
        
        Returns: list of arc dicts with arc_name, pokemon, promise, priority
        """
        arcs = []
        
        if not party:
            return arcs
        
        # Track Pokemon we've already created arcs for
        arc_pokemon = set()
        
        # 1. Evolution Watch — Pokemon close to evolution
        for i, poke in enumerate(party):
            if not poke.get('species'):
                continue
            species_id = poke.get('species', 0)
            level = poke.get('level', 0)
            species_name = self.species_names.get(species_id, f"Pokemon_{species_id}")
            
            # Check stage 1 evolutions
            if species_id in self.EVOLUTION_LEVELS:
                evo_level = self.EVOLUTION_LEVELS[species_id]
                if level >= evo_level - 3 and level < evo_level:
                    arcs.append({
                        'arc_name': f'{species_name} Evolution',
                        'pokemon': species_name,
                        'status': 'PENDING',
                        'promise': f'When {species_name} evolves (L{evo_level}), give visible reward to celebrate',
                        'priority': 'HIGH'
                    })
                    arc_pokemon.add(species_id)
            
            # Check stage 2 evolutions
            if species_id in self.EVOLUTION_LEVELS_STAGE2:
                evo_level = self.EVOLUTION_LEVELS_STAGE2[species_id]
                if level >= evo_level - 3 and level < evo_level:
                    arcs.append({
                        'arc_name': f'{species_name} Final Form',
                        'pokemon': species_name,
                        'status': 'PENDING',
                        'promise': f'Final evolution at L{evo_level} — make it special (shiny/move/item)',
                        'priority': 'HIGH'
                    })
                    arc_pokemon.add(species_id)
        
        # 2. MVP Recognition — Pokemon leading many battles
        trust = player_profile.get('pokemon_trust', {})
        for species_id, data in trust.items():
            if int(species_id) in arc_pokemon:
                continue
            battles_led = data.get('battles_led', 0)
            battles_won = data.get('battles_won', 0)
            pokemon_name = data.get('name', 'Unknown')
            
            if battles_led >= 5 and battles_won >= 3:
                # Already a leader — create recognition arc
                arcs.append({
                    'arc_name': f'{pokemon_name} Leadership',
                    'pokemon': pokemon_name,
                    'status': 'PENDING',
                    'promise': f'{pokemon_name} has led {battles_led} battles. Recognize their leadership with a signature item or move',
                    'priority': 'MEDIUM'
                })
                arc_pokemon.add(int(species_id))
        
        # 3. Comeback Hero — Pokemon with high comeback ratio
        for species_id, data in trust.items():
            if int(species_id) in arc_pokemon:
                continue
            comebacks = data.get('comebacks', 0)
            pokemon_name = data.get('name', 'Unknown')
            
            if comebacks >= 2:
                arcs.append({
                    'arc_name': f'{pokemon_name} the Resilient',
                    'pokemon': pokemon_name,
                    'status': 'PENDING',
                    'promise': f'{pokemon_name} has {comebacks} comebacks. Next clutch win gets Focus Band or special recognition',
                    'priority': 'MEDIUM'
                })
                arc_pokemon.add(int(species_id))
        
        # Limit to 3 arcs maximum per generation
        return arcs[:3]
    
    def add_arcs_to_playthrough(self, new_arcs: list) -> int:
        """
        Add generated arcs to PLAYTHROUGH.md ARC LEDGER.
        
        Returns: number of arcs added
        """
        if not new_arcs:
            return 0
        
        if not self.playthrough_path.exists():
            return 0
        
        # Check cooldown
        current_time = time.time()
        if current_time - self.last_generation_time < self.GENERATION_COOLDOWN:
            return 0
        
        try:
            content = self.playthrough_path.read_text()
            
            # Find the ARC LEDGER table end (the line before ---)
            lines = content.split('\n')
            insert_index = None
            
            for i, line in enumerate(lines):
                # Find last row of the ARC LEDGER table
                if line.strip().startswith('|') and '|' in line and 'Arc' not in line and '---' not in line:
                    # This is a data row
                    insert_index = i + 1
                elif insert_index and (line.strip().startswith('<!--') or line.strip().startswith('---') or line.strip() == ''):
                    # Found end of table
                    break
            
            if insert_index is None:
                return 0
            
            # Format new arcs as table rows
            new_rows = []
            for arc in new_arcs:
                row = f"| {arc['arc_name']} | {arc['pokemon']} | {arc['status']} | {arc['promise']} | {arc['priority']} |"
                new_rows.append(row)
            
            # Insert new rows
            for j, row in enumerate(new_rows):
                lines.insert(insert_index + j, row)
            
            # Write back
            self.playthrough_path.write_text('\n'.join(lines))
            self.last_generation_time = current_time
            
            return len(new_arcs)
        
        except Exception as e:
            print(f"[ARC-GEN] Error adding arcs: {e}")
            return 0
    
    def maybe_generate_arcs(self, pending_arcs: list, party: list, player_profile: dict, battle_history: list) -> list:
        """
        Check if new arcs are needed and generate them if so.
        
        This is the main entry point called by the daemon.
        
        Returns: list of generated arcs (empty if none generated)
        """
        if not self.needs_new_arcs(pending_arcs):
            return []
        
        new_arcs = self.generate_arcs(party, player_profile, battle_history)
        
        if new_arcs:
            added = self.add_arcs_to_playthrough(new_arcs)
            if added > 0:
                print(f"[ARC-GEN] Generated {added} new story arcs:")
                for arc in new_arcs[:added]:
                    print(f"  📖 {arc['arc_name']} ({arc['pokemon']}) — {arc['priority']}")
            return new_arcs[:added]
        
        return []


class RewardValidator:
    """
    Issue #24 — Reward Command Validation (AgentDropoutV2-inspired, arxiv 2602.23258).

    The "rectify-or-reject" pattern: intercept agent outputs before they propagate.
    Validates GM commands before execution to catch invalid parameters:
    - Slot indices (0-5 for party)
    - Move IDs (1-354 for Gen 3)
    - EV stat names (HP, ATK, DEF, SPA, SPD, SPE)
    - IV ranges (0-31)
    - Basic syntax

    Returns (is_valid, error_message, corrected_command) tuple.
    If correctable, returns the fixed command. If not, returns None with error message.
    """

    # Valid EV stat names (case-insensitive match)
    VALID_STATS = {'HP', 'ATK', 'DEF', 'SPA', 'SPD', 'SPE',
                   'ATTACK', 'DEFENSE', 'SP_ATK', 'SP_DEF', 'SPEED',
                   'SPATK', 'SPDEF'}

    # Gen 3 move ID range (1-354, 0 is None)
    MAX_MOVE_ID = 354

    # Gen 3 item ID range (roughly 1-377 for held items)
    MAX_ITEM_ID = 400

    # Party slot range
    MAX_SLOT = 5  # 0-5 = 6 Pokemon

    # Move slot range
    MAX_MOVE_SLOT = 3  # 0-3 = 4 moves

    def __init__(self):
        self.validation_log = []  # Track recent validations for debugging

    def validate(self, gm_call: str) -> tuple:
        """
        Validate a GM command and return (is_valid, error_msg, corrected_cmd).

        Returns:
            - (True, None, gm_call) if valid
            - (True, None, corrected) if auto-corrected
            - (False, error_message, None) if invalid and uncorrectable
        """
        import re

        if not gm_call or not gm_call.strip():
            return (True, None, gm_call)  # Empty = no-op, valid

        gm_call = gm_call.strip()

        # Extract function name and args
        match = re.match(r'GM\.(\w+)\(([^)]*)\)', gm_call)
        if not match:
            # Not a GM.func() call — might be legacy format, pass through
            return (True, None, gm_call)

        func_name = match.group(1)
        args_str = match.group(2)

        # Parse arguments (simple split, handles quoted strings minimally)
        args = [a.strip().strip('"\'') for a in args_str.split(',') if a.strip()]

        # Validate based on function
        try:
            if func_name == 'addEVs':
                # addEVs(slot, stat, amount)
                return self._validate_add_evs(gm_call, args)

            elif func_name == 'teachMove':
                # teachMove(slot, moveId, moveSlot)
                return self._validate_teach_move(gm_call, args)

            elif func_name == 'setIVs':
                # setIVs(slot, ivTable) or setIVs(slot, stat, value)
                return self._validate_set_ivs(gm_call, args)

            elif func_name == 'giveItem':
                # giveItem(slot, itemId)
                return self._validate_give_item(gm_call, args)

            elif func_name == 'setShiny':
                # setShiny(slot, isShiny)
                return self._validate_set_shiny(gm_call, args)

            elif func_name == 'addExperience':
                # addExperience(slot, amount)
                return self._validate_add_experience(gm_call, args)

            elif func_name == 'setFriendship':
                # setFriendship(slot, value)
                return self._validate_set_friendship(gm_call, args)

            else:
                # Unknown GM function — pass through (might be valid, we don't know)
                return (True, None, gm_call)

        except Exception as e:
            # Validation error — reject to be safe
            return (False, f"Validation error: {e}", None)

    def _validate_slot(self, slot_str: str) -> tuple:
        """Validate and parse a party slot (0-5)."""
        try:
            slot = int(slot_str)
            if 0 <= slot <= self.MAX_SLOT:
                return (True, slot)
            return (False, f"Slot {slot} out of range (0-{self.MAX_SLOT})")
        except ValueError:
            return (False, f"Invalid slot '{slot_str}' (must be integer 0-{self.MAX_SLOT})")

    def _validate_add_evs(self, gm_call: str, args: list) -> tuple:
        """Validate GM.addEVs(slot, stat, amount)"""
        if len(args) < 3:
            return (False, f"addEVs requires 3 args (slot, stat, amount), got {len(args)}", None)

        # Validate slot
        slot_valid, slot_result = self._validate_slot(args[0])
        if not slot_valid:
            return (False, slot_result, None)

        # Validate stat name
        stat = args[1].upper().strip('"\'')
        if stat not in self.VALID_STATS:
            # Try to auto-correct common mistakes
            corrections = {
                'SPECIAL_ATTACK': 'SPA', 'SPECIAL_DEFENSE': 'SPD',
                'SP.ATK': 'SPA', 'SP.DEF': 'SPD',
                'SPATTACK': 'SPA', 'SPDEFENSE': 'SPD',
            }
            if stat in corrections:
                corrected_stat = corrections[stat]
                corrected_call = f"GM.addEVs({args[0]}, '{corrected_stat}', {args[2]})"
                return (True, f"Auto-corrected stat '{stat}' → '{corrected_stat}'", corrected_call)
            return (False, f"Invalid stat '{stat}'. Valid: HP, ATK, DEF, SPA, SPD, SPE", None)

        # Validate amount
        try:
            amount = int(args[2])
            if amount < 0 or amount > 255:
                return (False, f"EV amount {amount} out of range (0-255)", None)
        except ValueError:
            return (False, f"Invalid EV amount '{args[2]}'", None)

        return (True, None, gm_call)

    def _validate_teach_move(self, gm_call: str, args: list) -> tuple:
        """Validate GM.teachMove(slot, moveId, moveSlot)"""
        if len(args) < 3:
            return (False, f"teachMove requires 3 args (slot, moveId, moveSlot), got {len(args)}", None)

        # Validate party slot
        slot_valid, slot_result = self._validate_slot(args[0])
        if not slot_valid:
            return (False, slot_result, None)

        # Validate move ID
        try:
            move_id = int(args[1])
            if move_id < 0 or move_id > self.MAX_MOVE_ID:
                return (False, f"Move ID {move_id} out of range (0-{self.MAX_MOVE_ID})", None)
        except ValueError:
            return (False, f"Invalid move ID '{args[1]}'", None)

        # Validate move slot
        try:
            move_slot = int(args[2])
            if move_slot < 0 or move_slot > self.MAX_MOVE_SLOT:
                return (False, f"Move slot {move_slot} out of range (0-{self.MAX_MOVE_SLOT})", None)
        except ValueError:
            return (False, f"Invalid move slot '{args[2]}'", None)

        return (True, None, gm_call)

    def _validate_set_ivs(self, gm_call: str, args: list) -> tuple:
        """Validate GM.setIVs(slot, ...) — various formats"""
        if len(args) < 2:
            return (False, f"setIVs requires at least 2 args, got {len(args)}", None)

        # Validate slot
        slot_valid, slot_result = self._validate_slot(args[0])
        if not slot_valid:
            return (False, slot_result, None)

        # If 3 args: setIVs(slot, stat, value)
        if len(args) == 3:
            stat = args[1].upper().strip('"\'')
            if stat not in self.VALID_STATS:
                return (False, f"Invalid IV stat '{stat}'", None)
            try:
                iv_val = int(args[2])
                if iv_val < 0 or iv_val > 31:
                    return (False, f"IV value {iv_val} out of range (0-31)", None)
            except ValueError:
                return (False, f"Invalid IV value '{args[2]}'", None)

        return (True, None, gm_call)

    def _validate_give_item(self, gm_call: str, args: list) -> tuple:
        """Validate GM.giveItem(slot, itemId)"""
        if len(args) < 2:
            return (False, f"giveItem requires 2 args (slot, itemId), got {len(args)}", None)

        # Validate slot
        slot_valid, slot_result = self._validate_slot(args[0])
        if not slot_valid:
            return (False, slot_result, None)

        # Validate item ID
        try:
            item_id = int(args[1])
            if item_id < 0 or item_id > self.MAX_ITEM_ID:
                return (False, f"Item ID {item_id} out of range (0-{self.MAX_ITEM_ID})", None)
        except ValueError:
            return (False, f"Invalid item ID '{args[1]}'", None)

        return (True, None, gm_call)

    def _validate_set_shiny(self, gm_call: str, args: list) -> tuple:
        """Validate GM.setShiny(slot, isShiny)"""
        if len(args) < 2:
            return (False, f"setShiny requires 2 args (slot, isShiny), got {len(args)}", None)

        # Validate slot
        slot_valid, slot_result = self._validate_slot(args[0])
        if not slot_valid:
            return (False, slot_result, None)

        # isShiny should be true/false or 1/0
        shiny_val = args[1].lower().strip()
        if shiny_val not in ('true', 'false', '1', '0'):
            return (False, f"Invalid shiny value '{args[1]}' (use true/false)", None)

        return (True, None, gm_call)

    def _validate_add_experience(self, gm_call: str, args: list) -> tuple:
        """Validate GM.addExperience(slot, amount)"""
        if len(args) < 2:
            return (False, f"addExperience requires 2 args (slot, amount), got {len(args)}", None)

        # Validate slot
        slot_valid, slot_result = self._validate_slot(args[0])
        if not slot_valid:
            return (False, slot_result, None)

        # Validate amount
        try:
            amount = int(args[1])
            if amount < 0 or amount > 1000000:  # Sanity cap
                return (False, f"Experience amount {amount} seems unreasonable", None)
        except ValueError:
            return (False, f"Invalid experience amount '{args[1]}'", None)

        return (True, None, gm_call)

    def _validate_set_friendship(self, gm_call: str, args: list) -> tuple:
        """Validate GM.setFriendship(slot, value)"""
        if len(args) < 2:
            return (False, f"setFriendship requires 2 args (slot, value), got {len(args)}", None)

        # Validate slot
        slot_valid, slot_result = self._validate_slot(args[0])
        if not slot_valid:
            return (False, slot_result, None)

        # Validate friendship value (0-255)
        try:
            value = int(args[1])
            if value < 0 or value > 255:
                return (False, f"Friendship {value} out of range (0-255)", None)
        except ValueError:
            return (False, f"Invalid friendship value '{args[1]}'", None)

        return (True, None, gm_call)


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
        self.agent_workspace = agent_workspace          # store for PLAYTHROUGH.md reads
        self.agent_memory_dir = agent_workspace / 'memory'  # where PLAYTHROUGH.md lives
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
        self.compressed_summaries = []  # Issue #14: KLong-inspired compressed history
        self.COMPRESSION_THRESHOLD = 20  # Compress when history reaches this size
        self.last_badge_count = 0  # Track badge milestones for compression triggers
        
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

        # GRIND_SUMMARY tracking (AgentConductor-inspired — issue #15)
        # When N events are skipped OR 10 minutes pass without an agent invoke,
        # synthesize a lightweight GRIND_SUMMARY to keep Maren's narrative continuity.
        self.last_agent_invoke_time = time.time()
        self.GRIND_BATCH_SIZE = 8       # Trigger after this many skipped events
        self.GRIND_TIMEOUT_SEC = 600    # Trigger after 10 min of silence

        # Issue #25 — Drought Breaker (Evaluating Stochasticity paper, arxiv 2602.23271)
        # Adds structure/constraints to reduce agent variance when drought is high.
        # At DROUGHT_WARNING_THRESHOLD: strong warning in prompt
        # At DROUGHT_BREAKER_THRESHOLD: force heuristic visible reward if agent says none
        self.DROUGHT_WARNING_THRESHOLD = 8   # Strong warning at 8+ consecutive invisible
        self.DROUGHT_BREAKER_THRESHOLD = 12  # Force heuristic at 12+ consecutive invisible

        # Issue #30 — Instruction Fade-Out Prevention (OPENDEV paper, arxiv 2603.05344)
        # Research shows agents drift from their instructions over time ("instruction fade-out").
        # Counter this with event-driven system reminders that restate core purpose.
        # Triggered when: high drought AND consecutive "none" responses AND no recent reminder.
        self.events_since_system_reminder = 0
        self.SYSTEM_REMINDER_INTERVAL = 10  # Min events between system reminders
        self.consecutive_none_count = 0     # Track consecutive "none" responses

        # Issue #32 — Response Format Compression (OPSDC + Reasoning Theater, arxiv 2603.05433/05488)
        # Research shows reasoning models often produce "performative" CoT that wastes tokens
        # without changing the answer. For low-uncertainty events, request abbreviated format.
        self.CONCISE_MODE_THRESHOLD = 0.4   # Uncertainty below this → request concise response

        # Issue #34 — Drift Detection System (SAHOO paper, arxiv 2603.06333)
        # SAHOO introduces "Goal Drift Index" to detect when agent behavior drifts from purpose.
        # Unlike Drought Breaker (consecutive tracking), this monitors the rolling "none" rate
        # across all recent decisions. High drift = Maren is systematically passive.
        # Triggered when: rolling_none_rate exceeds threshold over DRIFT_WINDOW decisions.
        self.DRIFT_WINDOW = 20            # Analyze last N decisions for drift
        self.DRIFT_THRESHOLD = 0.80       # Alert if >80% of recent decisions are "none"
        self.DRIFT_CRITICAL = 0.90        # Escalate at >90% none rate
        self.drift_history = []           # Recent decisions: 'visible', 'ev', 'none'
        
        # Battle tracking
        self.battle_history = []
        self.battle_buffer = []
        self.in_battle = False
        # Issue #29 — Contextual auto-arc detection for bag items
        self.last_battle_lead = None      # Pokemon name who led the last battle
        self.last_battle_lead_time = 0    # Timestamp of last battle end
        self.battle_start_time = None
        self.battle_start_hp = {}
        self.battle_start_levels = {}
        self.trainer_encounters = {}  # Track trainer battles for rematch detection {enemy_species_level: [timestamps]}
        
        # Ensure directories exist
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Issue #19 — Player Attribute Profiling (EXACT-inspired)
        self.player_profile = PlayerProfileTracker(
            profile_path=self.state_dir / 'player_profile.json',
            species_names=self.species_names,
        )

        # Issue #20 — Decision Logger (MAS-on-the-Fly phase 1: data collection)
        self.decision_logger = DecisionLogger(
            log_path=self.state_dir / 'decisions.jsonl',
        )

        # Issue #37 — Trajectory Learning (IBM arxiv 2603.10600-inspired)
        # Extracts strategic insights from past decisions for prompt injection
        self.trajectory_learner = TrajectoryLearner(
            decisions_path=self.state_dir / 'decisions.jsonl',
        )

        # Issue #38 — Skill Extraction (XSkill-inspired, arxiv 2603.12056)
        # Extracts reusable procedural "skills" from successful decision patterns
        self.skill_extractor = SkillExtractor(
            decisions_path=self.state_dir / 'decisions.jsonl',
        )

        # Issue #40 — Auto-Arc Generation (Story Hook Detection)
        # When ARC LEDGER is nearly empty, generate new narrative arcs from team state
        self.arc_generator = ArcGenerator(
            playthrough_path=self.agent_memory_dir / 'PLAYTHROUGH.md',
            species_names=self.species_names,
        )

        # Issue #23 — Learning Directives ("Tell Me What To Learn", arxiv 2602.23201)
        narrative_config = config.get('narrative', {})
        custom_directives = narrative_config.get('learning_directives', None)
        self.learning_directives = LearningDirectives(directives=custom_directives)
        if custom_directives:
            self.log(f"📚 Loaded {len(custom_directives)} custom learning directives")

        # Issue #24 — Reward Command Validation (AgentDropoutV2-inspired, arxiv 2602.23258)
        # "Rectify-or-reject" pattern: validate GM commands before execution
        self.reward_validator = RewardValidator()

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
        
        # Load playthrough memory if exists (lives in agent workspace's memory dir)
        playthrough = agent_workspace / 'memory' / 'PLAYTHROUGH.md'
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
                    self.compressed_summaries = data.get('compressed_summaries', [])
                    self.last_badge_count = data.get('last_badge_count', 0)
                    total = len(self.session_history) + len(self.compressed_summaries)
                    self.log(f"📜 Loaded {len(self.session_history)} events + {len(self.compressed_summaries)} summaries")

                    # Startup compression: handle large legacy sessions that were never compressed.
                    # If session has accumulated many events before compression was implemented,
                    # compress now in multiple passes until below threshold.
                    if len(self.session_history) >= self.COMPRESSION_THRESHOLD * 2:
                        original_count = len(self.session_history)
                        passes = 0
                        while len(self.session_history) >= self.COMPRESSION_THRESHOLD * 2:
                            self._compress_session_history(trigger='startup')
                            passes += 1
                            if passes > 20:  # Safety limit
                                break
                        C = Colors
                        self.log(
                            f"{C.CYAN}📦 STARTUP COMPRESS{C.RESET}  "
                            f"{original_count} → {len(self.session_history)} events "
                            f"({len(self.compressed_summaries)} summaries, {passes} passes)"
                        )
            except Exception as e:
                self.log(f"⚠️ Failed to load session history: {e}")
                self.session_history = []
                self.compressed_summaries = []
        else:
            self.log("📝 Starting new session")
    
    def _save_session_history(self):
        """Save session history to file for next run"""
        if self.session_persistent:
            try:
                session_data = {
                    'started_at': datetime.fromtimestamp(self.session_start).isoformat(),
                    'history': self.session_history,
                    'compressed_summaries': self.compressed_summaries,
                    'last_badge_count': self.last_badge_count,
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

    def _compress_session_history(self, trigger: str = 'threshold'):
        """
        Issue #14 — Session history compression (KLong-inspired, arxiv 2602.17547).

        Compresses the oldest half of session history into a structured summary.
        Triggered when history exceeds COMPRESSION_THRESHOLD or at badge milestones.

        This ensures important early-game arcs aren't lost in long playthroughs
        while keeping recent history at full fidelity for immediate context.
        """
        if len(self.session_history) < self.COMPRESSION_THRESHOLD:
            return  # Not enough history to compress

        # Take the oldest half of history
        split_point = len(self.session_history) // 2
        old_history = self.session_history[:split_point]
        self.session_history = self.session_history[split_point:]

        # Extract key events and patterns from old history
        event_types = {}
        key_decisions = []
        visible_rewards = []
        arcs_mentioned = set()

        for entry in old_history:
            # Count event types
            etype = entry.get('event_type', 'unknown')
            event_types[etype] = event_types.get(etype, 0) + 1

            # Extract key decisions from responses
            response = entry.get('response', '')
            if 'ACTION:' in response:
                action_line = [l for l in response.split('\n') if 'ACTION:' in l]
                if action_line:
                    action = action_line[0].split('ACTION:')[1].strip()[:80]
                    if action.lower() != 'none' and 'GM.' in action:
                        key_decisions.append(action)

            # Look for arc mentions
            for arc_word in ['Ralts', 'Combusken', 'Lombre', 'shiny', 'Blaze Kick', 'Giga Drain']:
                if arc_word.lower() in response.lower():
                    arcs_mentioned.add(arc_word)

            # Track visible rewards
            if 'teachMove' in response or 'setShiny' in response or 'giveItem' in response:
                visible_rewards.append(etype)

        # Build summary
        summary_parts = []
        if event_types:
            top_events = sorted(event_types.items(), key=lambda x: -x[1])[:3]
            summary_parts.append(f"Events: {', '.join(f'{e}({c})' for e, c in top_events)}")
        if arcs_mentioned:
            summary_parts.append(f"Arcs active: {', '.join(sorted(arcs_mentioned))}")
        if key_decisions:
            summary_parts.append(f"Key actions: {len(key_decisions)} GM interventions")
        if visible_rewards:
            summary_parts.append(f"Visible rewards: {len(visible_rewards)}")

        compressed = {
            'type': 'history_summary',
            'covers': f"{len(old_history)} interactions",
            'compressed_at': trigger,
            'timestamp': datetime.now().isoformat(),
            'summary': ' | '.join(summary_parts) if summary_parts else 'Routine gameplay',
            'key_decisions': key_decisions[-5:] if key_decisions else [],
            'arcs': list(arcs_mentioned),
        }

        self.compressed_summaries.append(compressed)
        C = Colors
        self.log(f"{C.CYAN}📦 COMPRESSED{C.RESET}  {len(old_history)} events → summary #{len(self.compressed_summaries)}")
        self._save_session_history()
    
    def _add_to_session_history(self, event_type: str, agent_prompt: str, agent_response: str):
        """Record an agent interaction in session history"""
        if self.session_persistent:
            self.session_history.append({
                'timestamp': datetime.now().isoformat(),
                'event_type': event_type,
                'prompt': agent_prompt,
                'response': agent_response
            })
            
            # Issue #14: Trigger compression if history exceeds threshold
            if len(self.session_history) >= self.COMPRESSION_THRESHOLD:
                self._compress_session_history(trigger='threshold')
            else:
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
    
    def write_state_dump(self, data: dict):
        """
        Write full game state to state/current.txt for agent to read.
        Called on every event so it's always current.
        """
        state_file = self.state_dir / 'current.txt'
        lines = []
        lines.append(f"# CURRENT STATE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"# Auto-updated on every game event. Read this before taking actions.")
        lines.append("")
        
        # Player info
        lines.append("## PLAYER")
        lines.append(f"Name: {data.get('player_name', 'Unknown')}")
        play_time = data.get('play_time', {})
        lines.append(f"Play Time: {play_time.get('hours', 0)}h {play_time.get('minutes', 0)}m")
        lines.append(f"Money: ${data.get('money', 0):,}")
        lines.append(f"Badges: {data.get('badge_count', 0)}")
        lines.append(f"Location: Map {data.get('map_group', 0)}-{data.get('map_num', 0)} @ ({data.get('player_x', 0)}, {data.get('player_y', 0)})")
        lines.append("")
        
        # Party
        lines.append("## PARTY")
        party = data.get('party') or []
        for p in party:
            slot = p.get('slot', 0)
            species_id = p.get('species', 0)
            species_name = self.species_names.get(species_id, f"Species#{species_id}")
            nickname = p.get('nickname', species_name)
            level = p.get('level', 1)
            hp = p.get('current_hp', 0)
            max_hp = p.get('max_hp', 1)
            
            # Status
            status_val = p.get('status', 0)
            status_str = ""
            if status_val & 0x07: status_str = " [SLP]"
            elif status_val & 0x08: status_str = " [PSN]"
            elif status_val & 0x10: status_str = " [BRN]"
            elif status_val & 0x20: status_str = " [FRZ]"
            elif status_val & 0x40: status_str = " [PAR]"
            elif status_val & 0x80: status_str = " [TOX]"
            
            lines.append(f"[{slot}] {nickname} ({species_name}) L{level} | HP {hp}/{max_hp}{status_str}")
            
            # Moves
            moves = p.get('moves', [0, 0, 0, 0])
            pp = p.get('pp', [0, 0, 0, 0])
            move_strs = []
            for i, move_id in enumerate(moves):
                if move_id > 0:
                    move_name = MOVE_NAMES.get(move_id, f"Move#{move_id}")
                    move_strs.append(f"{move_name}({pp[i] if i < len(pp) else '?'})")
            lines.append(f"    Moves: [{', '.join(move_strs)}]")
            lines.append(f"    Move IDs: {moves}")
            
            # Stats
            lines.append(f"    Stats: ATK {p.get('attack', 0)} | DEF {p.get('defense', 0)} | SPD {p.get('speed', 0)} | SPA {p.get('sp_attack', 0)} | SPD {p.get('sp_defense', 0)}")
            
            # EVs
            evs = p.get('evs', {})
            if evs:
                lines.append(f"    EVs: HP {evs.get('hp', 0)} | ATK {evs.get('attack', 0)} | DEF {evs.get('defense', 0)} | SPD {evs.get('speed', 0)} | SPA {evs.get('sp_attack', 0)} | SPD {evs.get('sp_defense', 0)}")
            
            # IVs
            ivs = p.get('ivs', {})
            if ivs:
                lines.append(f"    IVs: HP {ivs.get('hp', 0)} | ATK {ivs.get('attack', 0)} | DEF {ivs.get('defense', 0)} | SPD {ivs.get('speed', 0)} | SPA {ivs.get('sp_attack', 0)} | SPD {ivs.get('sp_defense', 0)}")
            
            # Nature + held item
            nature_id = p.get('nature', 0)
            nature_names = ['Hardy', 'Lonely', 'Brave', 'Adamant', 'Naughty', 'Bold', 'Docile', 'Relaxed', 'Impish', 'Lax', 'Timid', 'Hasty', 'Serious', 'Jolly', 'Naive', 'Modest', 'Mild', 'Quiet', 'Bashful', 'Rash', 'Calm', 'Gentle', 'Sassy', 'Careful', 'Quirky']
            nature_name = nature_names[nature_id] if nature_id < len(nature_names) else f"Nature#{nature_id}"
            held = p.get('held_item', 0)
            held_str = f"Item#{held}" if held > 0 else "None"
            lines.append(f"    Nature: {nature_name} | Held: {held_str}")
            lines.append(f"    EXP: {p.get('experience', 0):,}")
            lines.append("")
        
        # Bag items (summary)
        lines.append("## BAG (first 20 items)")
        bag = (data.get('bag_items') or [])[:20]
        for item in bag:
            lines.append(f"  Item#{item.get('id', 0)} x{item.get('qty', 0)}")
        if not bag:
            lines.append("  (empty or not readable)")
        lines.append("")
        
        # Battle state
        lines.append("## BATTLE STATE")
        if data.get('in_battle', False):
            lines.append("In Battle: YES")
            enemy = data.get('enemy_pokemon')
            if enemy:
                enemy_species = self.species_names.get(enemy.get('species', 0), f"Species#{enemy.get('species', 0)}")
                lines.append(f"Enemy: {enemy_species} L{enemy.get('level', '?')} | HP {enemy.get('hp', '?')}/{enemy.get('maxHp', '?')}")
                lines.append(f"Enemy Stats: ATK {enemy.get('attack', '?')} | DEF {enemy.get('defense', '?')} | SPD {enemy.get('speed', '?')}")
        else:
            lines.append("In Battle: NO")
        
        # Write atomically
        tmp_file = state_file.with_suffix('.tmp')
        with open(tmp_file, 'w') as f:
            f.write('\n'.join(lines))
        tmp_file.rename(state_file)
    
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
        if event_type in ('BADGE_OBTAINED', 'TRAINER_REMATCH', 'GRIND_SUMMARY'):
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
        
        # Issue #35 — Exploration Pre-filtering (data-driven, arxiv decision analysis)
        # Analysis of decisions.jsonl showed 97% none rate on EXPLORATION_SUMMARY.
        # Most exploration events are truly routine and don't warrant agent reasoning.
        # Only invoke agent when exploration has narrative potential.
        if event_type == 'EXPLORATION_SUMMARY':
            return self._score_exploration_uncertainty(context)
        
        # Unknown events — medium uncertainty
        return 0.5
    
    def should_invoke_agent(self, event_type: str, context: dict, threshold: float = 0.15) -> bool:
        """
        Determine if agent should be invoked for this event.
        Threshold 0.15 (low) means most events invoke the agent — skips only very routine
        wild battles (uncertainty 0.2 but threshold 0.15 still passes them).
        Raise threshold toward 0.4 to be more selective.
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

    def _calculate_drift_score(self) -> dict:
        """
        Issue #34 — Drift Detection System (SAHOO paper, arxiv 2603.06333).
        
        Calculate the "Goal Drift Index" — how much Maren's behavior has drifted
        from her purpose (making the game feel alive).
        
        Unlike Drought Breaker (consecutive), this measures the rolling "none" rate
        across recent decisions. A high none rate indicates systematic passivity.
        
        Returns: dict with drift_score, severity, and breakdown by event type
        """
        window = self.drift_history[-self.DRIFT_WINDOW:] if self.drift_history else []
        
        if len(window) < 5:
            # Not enough data for meaningful drift detection
            return {'drift_score': 0.0, 'severity': 'none', 'count': len(window)}
        
        # Calculate overall none rate
        none_count = sum(1 for r in window if r == 'none')
        ev_count = sum(1 for r in window if r == 'ev')
        visible_count = sum(1 for r in window if r == 'visible')
        total = len(window)
        
        # EVs count as "invisible" from the player's perspective
        invisible_count = none_count + ev_count
        drift_score = invisible_count / total
        
        # Determine severity
        if drift_score >= self.DRIFT_CRITICAL:
            severity = 'critical'
        elif drift_score >= self.DRIFT_THRESHOLD:
            severity = 'warning'
        else:
            severity = 'normal'
        
        return {
            'drift_score': round(drift_score, 3),
            'severity': severity,
            'count': total,
            'none': none_count,
            'ev': ev_count,
            'visible': visible_count,
        }

    def _score_exploration_uncertainty(self, context: dict) -> float:
        """
        Issue #35 — Exploration Pre-filtering (data-driven optimization).
        
        Analysis of decisions.jsonl showed 97% none rate on EXPLORATION_SUMMARY.
        Most exploration events are truly routine and don't warrant agent reasoning:
        - Collecting prize money
        - Using repels
        - Talking to random NPCs
        - Surfing between routes
        
        Only invoke agent when exploration has genuine narrative potential:
        - Party composition changed (Pokemon deposited/withdrawn)
        - Large item gain (>5 items — stocking up)
        - Significant money event (>$10k gain/loss)
        - Pending arcs mention exploration-related triggers
        - High drought (Maren needs to act SOMEWHERE)
        
        Returns: uncertainty score (0-1). Below threshold = skip agent.
        """
        state = context.get('state', {})
        summary = context.get('summary', '').lower()
        
        score = 0.0  # Start with lowest (routine)
        
        # RARE/CAUGHT keywords — always high (original behavior)
        if 'rare' in summary or 'caught' in summary:
            return 0.9
        
        # Party composition change — deposit/withdrawal has narrative weight
        # Check if party size changed from last known state
        current_party = state.get('party', [])
        current_party_size = len([p for p in current_party if p.get('species', 0) > 0])
        if hasattr(self, '_last_party_size') and current_party_size != self._last_party_size:
            score = max(score, 0.7)  # Party change is significant
        self._last_party_size = current_party_size
        
        # Large item gain — stocking up for something important
        items_gained = state.get('itemsGained', 0)
        if items_gained >= 5:
            score = max(score, 0.5)  # Notable item gain
        
        # Large money event — $10k+ is significant
        money_change = abs(state.get('moneyChange', 0))
        if money_change >= 10000:
            score = max(score, 0.4)  # Big financial event
        
        # High drought — Maren hasn't acted in a while, any event could be the one
        if self.ev_drought_count >= self.DROUGHT_WARNING_THRESHOLD:
            score = max(score, 0.6)  # Drought pressure elevates importance
        
        # Critical drift — agent is systematically passive, force more invocations
        drift = self._calculate_drift_score()
        if drift.get('severity') == 'critical':
            score = max(score, 0.5)
        
        # Pending IMMEDIATE arcs — always be ready to close them
        arcs = self._get_pending_arcs_structured()
        has_immediate = any(a['status'] == 'IMMEDIATE' for a in arcs)
        if has_immediate:
            score = max(score, 0.5)
        
        # If no special factors, exploration is routine (low uncertainty)
        # Default: 0.0 which is below threshold (0.15), so agent will be skipped
        # But to allow occasional sampling, give a baseline of 0.1
        return max(score, 0.1)

    def _get_heuristic_reward(self, event_type: str) -> str:
        """
        Issue #25 — Drought Breaker heuristic reward generator.
        
        When agent gives "none" at critical drought levels, generate a reasonable
        visible reward based on current game state. This ensures the player
        feels Maren's presence even when the agent is being too passive.
        
        Heuristics by event type:
        - BATTLE_SUMMARY: Bonus XP to the MVP (slot 0 usually led)
        - EXPLORATION_SUMMARY: Give a useful held item
        - GRIND_SUMMARY: Bonus XP to least-leveled party member
        - Default: Small XP bonus to lead Pokemon
        
        Returns: GM command string or None if no heuristic available
        """
        try:
            party = self.current_state.get('party', [])
            if not party:
                return None
            
            # Find best slot to reward
            lead_slot = 0
            lowest_level_slot = 0
            lowest_level = 100
            
            for i, poke in enumerate(party):
                level = poke.get('level', 100)
                if level < lowest_level:
                    lowest_level = level
                    lowest_level_slot = i
            
            # Common useful held items in Gen 3 (item IDs)
            # Leftovers=234, Shell Bell=253, Scope Lens=232, King's Rock=221
            # Quick Claw=217, Bright Powder=219, Focus Band=230
            HELD_ITEMS = [234, 253, 232, 221, 217, 219, 230]
            import random
            
            if event_type == 'BATTLE_SUMMARY':
                # Battle just ended — reward lead Pokemon with XP
                xp_amount = random.choice([150, 200, 250, 300])
                return f"GM.addExperience({lead_slot}, {xp_amount})"
            
            elif event_type == 'EXPLORATION_SUMMARY':
                # Exploring — give a useful held item to lead
                item_id = random.choice(HELD_ITEMS)
                return f"GM.giveItem({lead_slot}, {item_id})"
            
            elif event_type == 'GRIND_SUMMARY':
                # Long grind — help the underleveled Pokemon
                xp_amount = random.choice([200, 300, 400])
                return f"GM.addExperience({lowest_level_slot}, {xp_amount})"
            
            else:
                # Default: small XP to lead
                return f"GM.addExperience({lead_slot}, 100)"
                
        except Exception:
            return None
    
    def _get_pending_arcs_structured(self) -> list:
        """
        Extract pending arc payoffs from PLAYTHROUGH.md as structured dicts.

        Returns list of dicts with: arc_name, pokemon, status, promise, priority
        Used by _get_pending_arcs() for formatted injection and by
        _get_proactive_arc_suggestions() for A-MAC quality-aware prompting.
        """
        playthrough = self.agent_memory_dir / 'PLAYTHROUGH.md'
        pending = []

        try:
            if not playthrough.exists():
                return []

            text = playthrough.read_text()

            in_ledger = False
            header_seen = False
            separator_seen = False

            for line in text.split('\n'):
                stripped = line.strip()

                if stripped.startswith('## ARC LEDGER'):
                    in_ledger = True
                    continue

                if in_ledger and stripped.startswith('## ') and 'ARC LEDGER' not in stripped:
                    break

                if not in_ledger:
                    continue

                if stripped.startswith('<!--'):
                    continue

                if '| Arc' in stripped and '| Status' in stripped:
                    header_seen = True
                    continue

                if header_seen and not separator_seen and stripped.startswith('|') and '---' in stripped:
                    separator_seen = True
                    continue

                if header_seen and separator_seen and stripped.startswith('|'):
                    parts = [p.strip() for p in stripped.strip('|').split('|')]
                    if len(parts) >= 4:
                        arc_name  = parts[0].strip()
                        pokemon   = parts[1].strip()
                        status    = parts[2].strip().upper()
                        promise   = parts[3].strip()
                        priority  = parts[4].strip().upper() if len(parts) > 4 else 'MEDIUM'

                        if status in ('PENDING', 'IMMEDIATE'):
                            pending.append({
                                'arc_name': arc_name,
                                'pokemon': pokemon,
                                'status': status,
                                'promise': promise,
                                'priority': priority,
                            })
        except Exception:
            pass

        return pending[:5]

    def _parse_arc_condition(self, promise: str) -> dict:
        """
        Issue #36 — Condition-Aware Arc Escalation (AutoAgent-inspired, arxiv 2603.09716).
        
        Parse numeric conditions from arc promises to enable closed-loop verification.
        AutoAgent's "closed-loop evolution" aligns intended actions with outcomes.
        
        Examples:
            "If Swellow leads 5+ wins" → {'type': 'wins', 'target': 5, 'pokemon': 'Swellow'}
            "3+ battles with Blaziken leading" → {'type': 'battles_led', 'target': 3}
            "After 10 battles" → {'type': 'battles', 'target': 10}
        
        Returns: dict with 'type', 'target', and optional context, or empty dict if no condition.
        """
        import re
        
        # Pattern: "N+" or "N +" followed by keyword
        patterns = [
            # "5+ wins" or "leads 5+ wins"
            (r'(\d+)\+?\s*wins?', 'wins'),
            # "leads 5+ battles" or "5+ battles leading"
            (r'(\d+)\+?\s*battles?\s*(?:led|leading)', 'battles_led'),
            (r'leads?\s*(\d+)\+?\s*(?:battles?|wins?)', 'battles_led'),
            # "after N battles"
            (r'after\s*(\d+)\+?\s*battles?', 'battles'),
            # "N+ close calls"
            (r'(\d+)\+?\s*close\s*calls?', 'close_calls'),
        ]
        
        promise_lower = promise.lower()
        
        for pattern, condition_type in patterns:
            match = re.search(pattern, promise_lower)
            if match:
                target = int(match.group(1))
                return {
                    'type': condition_type,
                    'target': target,
                    'raw_match': match.group(0)
                }
        
        return {}

    def _check_arc_progress(self, arc: dict) -> dict:
        """
        Issue #36 — Condition-Aware Arc Escalation (AutoAgent-inspired, arxiv 2603.09716).
        
        Check arc condition against PlayerProfileTracker to determine progress.
        Creates closed-loop between arc promises and actual game state.
        
        Args:
            arc: dict from _get_pending_arcs_structured() with arc_name, pokemon, promise, etc.
        
        Returns: dict with:
            - 'has_condition': bool
            - 'current': int (current value from profile)
            - 'target': int (target from promise)
            - 'met': bool (current >= target)
            - 'progress_str': str (e.g., "3/5 wins")
        """
        condition = self._parse_arc_condition(arc.get('promise', ''))
        
        if not condition:
            return {'has_condition': False}
        
        pokemon_name = arc.get('pokemon', '').lower()
        condition_type = condition['type']
        target = condition['target']
        
        # Look up Pokemon in player profile
        profile = self.player_profile.profile
        trust = profile.get('pokemon_trust', {})
        
        # Find matching Pokemon (case-insensitive)
        current = 0
        matched_pokemon = None
        
        for species_id, data in trust.items():
            if data.get('name', '').lower() == pokemon_name:
                matched_pokemon = data
                break
        
        if matched_pokemon:
            if condition_type == 'wins':
                current = matched_pokemon.get('battles_won', 0)
            elif condition_type in ('battles_led', 'battles'):
                current = matched_pokemon.get('battles_led', 0)
        
        met = current >= target
        
        # Build progress string
        if condition_type == 'wins':
            progress_str = f"{current}/{target} wins"
        elif condition_type in ('battles_led', 'battles'):
            progress_str = f"{current}/{target} battles"
        elif condition_type == 'close_calls':
            progress_str = f"{current}/{target} close calls"
        else:
            progress_str = f"{current}/{target}"
        
        return {
            'has_condition': True,
            'current': current,
            'target': target,
            'met': met,
            'progress_str': progress_str,
            'condition_type': condition_type,
        }

    def _get_pending_arcs_with_progress(self) -> list:
        """
        Issue #36 — Condition-Aware Arc Escalation (AutoAgent-inspired, arxiv 2603.09716).
        
        Get pending arcs enriched with progress tracking from PlayerProfileTracker.
        For arcs with numeric conditions, includes current progress (e.g., "3/5 wins").
        For arcs where condition IS met, marks them for urgent attention.
        
        Returns: list of formatted strings with arc info + progress
        """
        arcs = self._get_pending_arcs_structured()
        result = []
        
        for arc in arcs:
            progress = self._check_arc_progress(arc)
            
            urgency = '🔴 IMMEDIATE' if arc['status'] == 'IMMEDIATE' else '🟡 PENDING'
            base = f"{urgency} [{arc['priority']}] {arc['arc_name']} ({arc['pokemon']}): {arc['promise']}"
            
            if progress.get('has_condition'):
                if progress['met']:
                    # Condition MET — elevate urgency
                    base += f"\n   ✅ CONDITION MET: {progress['progress_str']} — READY TO CLOSE!"
                else:
                    # Show progress toward condition
                    base += f"\n   📊 Progress: {progress['progress_str']}"
            
            result.append(base)
        
        return result[:5]

    def _get_proactive_arc_suggestions(self, event_type: str, ctx: dict) -> str:
        """
        Issue #33 — Quality-Aware Arc Prompting (A-MAC-inspired, arxiv 2603.05549).

        For high-uncertainty events (trainer battles, badges, close calls), proactively
        suggest which pending arcs could be closed by THIS specific event.

        A-MAC research: "content type prior is the most influential factor" for memory admission.
        Applied here: event type determines HOW arcs are presented, not just WHETHER.

        Low-uncertainty events: passive arc listing (current behavior)
        High-uncertainty events: active arc matching with specific suggestions

        Returns: formatted suggestion block or empty string.
        """
        arcs = self._get_pending_arcs_structured()
        if not arcs:
            return ''

        # Only do proactive suggestions for high-uncertainty events
        uncertainty = self.score_event_uncertainty(event_type, ctx)
        if uncertainty < 0.6:
            return ''  # Low uncertainty — use passive injection instead

        # Extract context clues from the event
        context_pokemon = set()
        context_keywords = set()

        # From battle buffer (who fought, what happened)
        buffer = ctx.get('buffer', [])
        for event in buffer:
            ev = event.get('event', '')
            if ev == 'START':
                context_keywords.add('battle')
                if event.get('is_trainer'):
                    context_keywords.add('trainer')
                if event.get('is_rematch'):
                    context_keywords.add('rematch')
            elif ev == 'END':
                if event.get('was_close'):
                    context_keywords.add('close_call')
                    context_keywords.add('clutch')

        # From current party — who's in the team?
        party = ctx.get('state', {}).get('party', [])
        for p in party:
            species = p.get('species', 0)
            name = self.get_species_name(species).lower()
            if name and not name.startswith('pokemon #'):
                context_pokemon.add(name)

        # From battle dialogue — look for Pokemon names mentioned
        dialogue = ctx.get('battle_dialogue', [])
        dialogue_text = ' '.join(dialogue[-20:]).lower()

        # Match arcs to current context
        matched_arcs = []
        for arc in arcs:
            arc_pokemon = arc['pokemon'].lower()
            arc_promise = arc['promise'].lower()

            # Check if arc's Pokemon is in current party or mentioned in battle
            pokemon_match = (
                arc_pokemon in context_pokemon or
                arc_pokemon in dialogue_text or
                any(arc_pokemon in p.lower() for p in context_pokemon)
            )

            # Check for keyword matches (close_call, trainer, etc.)
            keyword_match = any(kw in arc_promise for kw in context_keywords)

            # IMMEDIATE arcs are always suggested
            is_immediate = arc['status'] == 'IMMEDIATE'
            
            # Issue #36 — Arcs with MET conditions are always suggested
            # If the player has earned this arc, we should be looking to close it
            progress = self._check_arc_progress(arc)
            condition_met = progress.get('met', False)

            if pokemon_match or keyword_match or is_immediate or condition_met:
                matched_arcs.append(arc)

        if not matched_arcs:
            return ''

        # Build proactive suggestion block
        lines = []
        lines.append('═══════════════════════════════════════════════════════')
        lines.append('🎯 ARC OPPORTUNITY DETECTED — THIS EVENT MATCHES PENDING ARCS')
        lines.append('═══════════════════════════════════════════════════════')
        lines.append('')

        for arc in matched_arcs:
            # Issue #36 — Include progress info from PlayerProfileTracker
            progress = self._check_arc_progress(arc)
            
            urgency = '🔴 IMMEDIATE' if arc['status'] == 'IMMEDIATE' else '🟡 PENDING'
            lines.append(f"{urgency} [{arc['priority']}]: {arc['arc_name']}")
            lines.append(f"   Pokemon: {arc['pokemon']}")
            lines.append(f"   Promise: {arc['promise']}")
            
            # Show progress if arc has numeric condition
            if progress.get('has_condition'):
                if progress['met']:
                    lines.append(f"   ✅ CONDITION MET: {progress['progress_str']} — READY TO CLOSE!")
                else:
                    lines.append(f"   📊 Progress: {progress['progress_str']}")

            # Extract GM command from promise if present
            import re
            gm_match = re.search(r'GM\.\w+\([^)]*\)', arc['promise'])
            if gm_match:
                lines.append(f"   → Suggested action: {gm_match.group(0)}")
            lines.append('')

        lines.append('This event is a strong candidate to close an arc.')
        lines.append('If any arc matches the moment, CLOSE IT NOW. Include:')
        lines.append('  ACTION: <GM.xxx>')
        lines.append('  ARC_CLOSED: <arc name>')
        lines.append('═══════════════════════════════════════════════════════')

        return '\n'.join(lines)

    def _get_pending_arcs(self) -> list:
        """
        Extract pending arc payoffs from PLAYTHROUGH.md.

        Primary: parses the structured ## ARC LEDGER markdown table.
        Rows with Status = PENDING or IMMEDIATE are returned as clear instructions.
        
        Issue #36 — Now includes progress tracking from PlayerProfileTracker.
        For arcs with numeric conditions (e.g., "5+ wins"), shows current progress.

        Fallback: keyword scan for legacy freeform arc markers (pre-ledger format).

        Returns up to 5 pending arcs for injection into the agent prompt.
        """
        # PLAYTHROUGH.md lives in the agent's memory dir, not the daemon's memory dir.
        # Bug fix: was reading daemon/memory/PLAYTHROUGH.md (empty) instead of
        # agent/memory/PLAYTHROUGH.md (the real file).
        playthrough = self.agent_memory_dir / 'PLAYTHROUGH.md'
        pending = []

        try:
            if not playthrough.exists():
                return []

            # Issue #36 — Use progress-aware method (AutoAgent-inspired closed-loop)
            # This enriches arcs with actual progress from PlayerProfileTracker
            pending = self._get_pending_arcs_with_progress()

            if pending:
                return pending[:5]

            # ── Fallback: legacy freeform markers ─────────────────────────
            text = playthrough.read_text()
            if True:  # Always try fallback when no structured arcs found
                markers = [
                    'IMMEDIATE PAYOFF:',
                    'PENDING PAYOFF:',
                    'PENDING:',
                    'PAYOFF OWED:',
                    '→ immediate shiny',
                    '→ give it',
                    '→ teach',
                ]
                for line in text.split('\n'):
                    s = line.strip()
                    if len(s) < 20:
                        continue
                    if any(m.lower() in s.lower() for m in markers):
                        clean = s.lstrip('*- ').rstrip('*')
                        if clean:
                            pending.append(clean)

        except Exception:
            pass

        return pending[:5]

    def _get_relevant_narrative(self, event_type: str, max_chars: int = 1500) -> str:
        """
        Issue #21 — Context-relevant PLAYTHROUGH.md injection (quality > quantity).

        Research (arxiv 2602.20091): Irrelevant retrieved context actively harms
        LLM performance by polluting early-layer representations. Quality > quantity.

        Instead of dumping last 3000 chars, filter PLAYTHROUGH.md by event type:
        - BATTLE_SUMMARY → battle sections, whiteouts, rematches, poison arcs
        - BADGE_OBTAINED → badge/gym sections, milestone victories
        - POKEMON_CAUGHT → catch/evolution/team sections
        - MOVE_MASTERY → move learning, evolution, signature move sections
        - GRIND_SUMMARY → minimal (arc ledger provides hot context)

        Returns: filtered narrative text up to max_chars, or empty string.
        """
        playthrough = self.agent_memory_dir / 'PLAYTHROUGH.md'
        if not playthrough.exists():
            return ''

        try:
            text = playthrough.read_text()

            # Find the end of the ARC LEDGER section (skip the machine-readable table).
            # ARC LEDGER is at the TOP of the file; narrative content comes AFTER.
            # Look for the next ## header after ARC LEDGER, or the first --- separator.
            import re
            narrative_start = 0
            if '## ARC LEDGER' in text:
                ledger_idx = text.index('## ARC LEDGER')
                # Find the next ## header after ARC LEDGER (the narrative sections)
                rest = text[ledger_idx + 15:]  # Skip past "## ARC LEDGER" header
                next_section = re.search(r'\n## [^A]', rest)  # Next ## that's not ARC
                if next_section:
                    narrative_start = ledger_idx + 15 + next_section.start()
                else:
                    # Fallback: look for --- separator
                    sep_match = re.search(r'\n---\n', rest)
                    if sep_match:
                        narrative_start = ledger_idx + 15 + sep_match.end()

            text = text[narrative_start:].strip()
            if not text:
                return ''

            # Define relevance keywords per event type
            EVENT_KEYWORDS = {
                'BATTLE_SUMMARY': [
                    'battle', 'fight', 'fainted', 'whiteout', 'rematch',
                    'swept', 'crit', 'close call', 'poison', 'paralysis',
                    'KO', 'OHKO', 'victory', 'defeat', 'gym', 'trainer',
                    'Double Kick', 'Combusken', 'closer', 'clutch'
                ],
                'BADGE_OBTAINED': [
                    'badge', 'gym', 'leader', 'roxanne', 'brawly', 'wattson',
                    'flannery', 'norman', 'winona', 'tate', 'liza', 'wallace',
                    'milestone', 'victory', 'earned', 'dynamo', 'stone', 'knuckle'
                ],
                'POKEMON_CAUGHT': [
                    'caught', 'catch', 'evolve', 'evolution', 'team snapshot',
                    'party', 'shiny', 'rare', 'lotad', 'ralts', 'combusken',
                    'kirlia', 'lombre', 'nincada', 'taillow'
                ],
                'MOVE_MASTERY': [
                    'learned', 'move', 'mastery', 'signature', 'replaced',
                    'double kick', 'blaze kick', 'bulk up', 'confusion',
                    'absorb', 'giga drain', 'peck', 'wing attack'
                ],
                'TRAINER_REMATCH': [
                    'rematch', 'rival', 'may', 'wally', 'return', 'revenge',
                    'comeback', 'wall', 'second attempt', 'went back'
                ],
            }

            # GRIND_SUMMARY gets minimal context (arc ledger is enough)
            if event_type == 'GRIND_SUMMARY':
                return ''

            keywords = EVENT_KEYWORDS.get(event_type, EVENT_KEYWORDS['BATTLE_SUMMARY'])
            keywords_lower = [k.lower() for k in keywords]

            # Split into sections by ## headers
            sections = re.split(r'\n(?=## )', text)

            # Score and rank sections by relevance
            scored_sections = []
            for section in sections:
                if len(section.strip()) < 50:  # Skip tiny sections
                    continue
                section_lower = section.lower()
                score = sum(1 for kw in keywords_lower if kw in section_lower)
                if score > 0:
                    scored_sections.append((score, section.strip()))

            # Sort by score (highest first) and take best matches
            scored_sections.sort(key=lambda x: x[0], reverse=True)

            # Build result up to max_chars
            result_parts = []
            total_chars = 0
            for score, section in scored_sections:
                if total_chars + len(section) > max_chars:
                    # Try to fit a truncated version
                    remaining = max_chars - total_chars
                    if remaining > 200:
                        result_parts.append(section[:remaining] + '...')
                    break
                result_parts.append(section)
                total_chars += len(section) + 2  # +2 for newlines

            if not result_parts:
                return ''

            return '\n\n'.join(result_parts)

        except Exception:
            return ''

    def _close_arc(self, arc_name: str) -> bool:
        """
        Close a delivered arc in the ARC LEDGER within PLAYTHROUGH.md.

        Issue #17 — Arc delivery confirmation (MemoryArena-inspired).
        When Maren signals ARC_CLOSED: <name>, we find the matching row
        in the ARC LEDGER table and change its status to DELIVERED.

        Returns True if a matching arc was found and updated.
        """
        playthrough = self.agent_memory_dir / 'PLAYTHROUGH.md'
        if not playthrough.exists():
            return False

        try:
            text = playthrough.read_text()
            lines = text.split('\n')
            updated = False
            arc_name_lower = arc_name.lower().strip()

            # Find the ARC LEDGER table and look for a matching row
            in_ledger = False
            header_seen = False
            separator_seen = False

            for i, line in enumerate(lines):
                stripped = line.strip()

                if stripped.startswith('## ARC LEDGER'):
                    in_ledger = True
                    continue

                if in_ledger and stripped.startswith('## ') and 'ARC LEDGER' not in stripped:
                    break

                if not in_ledger:
                    continue

                if '| Arc' in stripped and '| Status' in stripped:
                    header_seen = True
                    continue

                if header_seen and not separator_seen and stripped.startswith('|') and '---' in stripped:
                    separator_seen = True
                    continue

                if header_seen and separator_seen and stripped.startswith('|'):
                    parts = [p.strip() for p in stripped.strip('|').split('|')]
                    if len(parts) >= 3:
                        row_arc = parts[0].strip().lower()
                        row_status = parts[2].strip().upper()
                        # Match on arc name (partial, case-insensitive) and only
                        # close PENDING or IMMEDIATE arcs
                        if (arc_name_lower in row_arc or row_arc in arc_name_lower) \
                                and row_status in ('PENDING', 'IMMEDIATE'):
                            # Replace status column with DELIVERED
                            parts[2] = 'DELIVERED'
                            new_row = '| ' + ' | '.join(parts) + ' |'
                            lines[i] = new_row
                            updated = True
                            C = Colors
                            self.log(
                                f"{C.BOLD}{C.GREEN}✅ ARC CLOSED: {parts[0].strip()}{C.RESET}"
                            )
                            break

            if updated:
                playthrough.write_text('\n'.join(lines))
                return True

        except Exception as e:
            self.log(f"⚠️ _close_arc failed: {e}")

        return False

    def _auto_close_arc_for_reward(self, gm_call: str) -> bool:
        """
        Auto-detect and close arcs when visible rewards match PENDING Pokemon.

        Issue #28 — Auto-Arc Detection (research: MOSAIC closed-loop pattern)
        Issue #29 — Contextual detection for bag items (GM.give)
        
        When a visible reward is given to a Pokemon and the agent didn't explicitly
        signal ARC_CLOSED, check if the Pokemon matches any PENDING arc and auto-close.

        For slot-based commands (teachMove, giveItem, etc.), we know which Pokemon.
        For bag commands (GM.give), we infer from the last battle lead if recent.

        This reduces agent burden and catches cases where appropriate rewards are
        given but the arc tag is forgotten.

        Returns True if an arc was auto-closed.
        """
        import re
        
        # Parse slot number from GM command
        slot_patterns = [
            r'GM\.teachMove\((\d+),',      # teachMove(slot, moveId, moveSlot)
            r'GM\.addExperience\((\d+),',  # addExperience(slot, amount)
            r'GM\.setIVs\((\d+),',         # setIVs(slot, stat, value)
            r'GM\.setShiny\((\d+),',       # setShiny(slot, isShiny)
            r'GM\.setFriendship\((\d+),',  # setFriendship(slot, value)
            r'GM\.giveItem\((\d+),',       # giveItem(slot, itemId) — held item
        ]
        
        pokemon_name = None
        
        # Try slot-based detection first
        slot = None
        for pattern in slot_patterns:
            match = re.search(pattern, gm_call)
            if match:
                slot = int(match.group(1))
                break
        
        if slot is not None:
            # Get Pokemon name from current party
            pokemon_name = self.get_party_pokemon_name(slot)
            if not pokemon_name or pokemon_name.startswith('Pokemon #'):
                pokemon_name = None  # Can't identify Pokemon from slot
        
        # Issue #29 — Fallback: for bag items (GM.give), use last battle lead
        # This handles cases like GM.give("charcoal", 1) given right after Blaziken sweeps
        if pokemon_name is None:
            bag_pattern = r'GM\.give\(["\']([^"\']+)["\'],\s*\d+'
            if re.search(bag_pattern, gm_call):
                # It's a bag item — check if we have a recent battle lead
                time_since_battle = time.time() - getattr(self, 'last_battle_lead_time', 0)
                last_lead = getattr(self, 'last_battle_lead', None)
                
                # Only use inference if battle was within 2 minutes
                if last_lead and time_since_battle < 120:
                    pokemon_name = last_lead
                    C = Colors
                    self.log(
                        f"{C.DIM}🔍 Inferring reward target: {pokemon_name} "
                        f"(led battle {time_since_battle:.0f}s ago){C.RESET}"
                    )
        
        if not pokemon_name:
            return False  # Can't determine target Pokemon
        
        pokemon_lower = pokemon_name.lower()
        
        # Get pending arcs and check for match
        playthrough = self.agent_memory_dir / 'PLAYTHROUGH.md'
        if not playthrough.exists():
            return False
        
        try:
            text = playthrough.read_text()
            lines = text.split('\n')
            
            # Find ARC LEDGER and check for matching Pokemon
            in_ledger = False
            header_seen = False
            separator_seen = False
            
            for i, line in enumerate(lines):
                stripped = line.strip()
                
                if stripped.startswith('## ARC LEDGER'):
                    in_ledger = True
                    continue
                
                if in_ledger and stripped.startswith('## ') and 'ARC LEDGER' not in stripped:
                    break
                
                if not in_ledger:
                    continue
                
                if '| Arc' in stripped and '| Status' in stripped:
                    header_seen = True
                    continue
                
                if header_seen and not separator_seen and stripped.startswith('|') and '---' in stripped:
                    separator_seen = True
                    continue
                
                if header_seen and separator_seen and stripped.startswith('|'):
                    parts = [p.strip() for p in stripped.strip('|').split('|')]
                    if len(parts) >= 3:
                        arc_name = parts[0].strip()
                        arc_pokemon = parts[1].strip().lower() if len(parts) > 1 else ''
                        row_status = parts[2].strip().upper()
                        
                        # Check if Pokemon matches and arc is PENDING/IMMEDIATE
                        if row_status in ('PENDING', 'IMMEDIATE') and \
                           (pokemon_lower in arc_pokemon or arc_pokemon in pokemon_lower):
                            # Found a match — close this arc
                            parts[2] = 'DELIVERED'
                            new_row = '| ' + ' | '.join(parts) + ' |'
                            lines[i] = new_row
                            playthrough.write_text('\n'.join(lines))
                            
                            C = Colors
                            self.log(
                                f"{C.BOLD}{C.CYAN}🔄 AUTO-ARC CLOSED: {arc_name} "
                                f"(reward given to {pokemon_name}){C.RESET}"
                            )
                            return True
            
        except Exception as e:
            self.log(f"⚠️ _auto_close_arc_for_reward failed: {e}")
        
        return False

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
            self.last_agent_invoke_time = time.time()  # Track for GRIND_SUMMARY timeout
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
                    arc_closed_name = None  # ARC_CLOSED tag if Maren signals delivery
                    for line in response_text.split('\n')[:20]:
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
                            elif line.startswith('ARC_CLOSED:'):
                                # Issue #17 — arc delivery confirmation tag
                                label = f"{C.BOLD}{C.GREEN}ARC✓{C.RESET}"
                                content = line.split(':', 1)[1].strip()
                                arc_closed_name = content
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

                    # Issue #17: Arc delivery confirmation — close the arc in PLAYTHROUGH.md
                    if arc_closed_name:
                        closed = self._close_arc(arc_closed_name)
                        if not closed:
                            self.log(f"{C.DIM}⚠️ ARC_CLOSED: no match found for '{arc_closed_name}'{C.RESET}")

                    # Classify reward for drought tracking (use first action or action_cmd)
                    classify_target = action_cmds[0] if action_cmds else action_cmd
                    reward_type = self._classify_reward(classify_target)
                    self.reward_history.append(reward_type)
                    if len(self.reward_history) > 10:
                        self.reward_history = self.reward_history[-10:]

                    # Issue #34 — Drift Detection System (SAHOO paper, arxiv 2603.06333)
                    # Track all decisions for rolling drift analysis
                    self.drift_history.append(reward_type)
                    if len(self.drift_history) > self.DRIFT_WINDOW * 2:
                        self.drift_history = self.drift_history[-self.DRIFT_WINDOW:]

                    if reward_type == 'visible':
                        self.ev_drought_count = 0
                        self.session_visible_rewards += 1
                        # Issue #30: Reset fade-out counters on visible reward
                        self.consecutive_none_count = 0
                    elif reward_type == 'ev':
                        self.ev_drought_count += 1
                        self.consecutive_none_count += 1  # EVs are invisible = "none" from player POV
                    else:
                        self.ev_drought_count += 1
                        self.consecutive_none_count += 1

                    # Issue #30 — Track events for system reminder cadence
                    self.events_since_system_reminder += 1

                    # Issue #20 — Log decision for future pattern retrieval (MAS-on-the-Fly)
                    final_action = action_cmds[0] if action_cmds else (action_cmd or 'none')
                    self.decision_logger.log(
                        event_type=event_type,
                        action_cmd=final_action,
                        reward_type=reward_type,
                        drought=self.ev_drought_count,
                        arcs_active=len(self._get_pending_arcs()),
                        session_visible=self.session_visible_rewards,
                        arc_closed=arc_closed_name,
                        response_snippet=response_text[:200],
                    )

                    # Execute all extracted GM calls (with validation — Issue #24)
                    for gm_call in action_cmds:
                        # Issue #24: Rectify-or-reject validation (AgentDropoutV2-inspired)
                        is_valid, error_msg, corrected = self.reward_validator.validate(gm_call)
                        
                        if not is_valid:
                            # Reject invalid command
                            print(f"  {C.RED}✗ REJECTED: {gm_call}{C.RESET}")
                            print(f"    {C.DIM}→ {error_msg}{C.RESET}")
                            continue
                        
                        # Use corrected command if auto-fixed
                        final_cmd = corrected or gm_call
                        if corrected and corrected != gm_call:
                            print(f"  {C.YELLOW}⚠ AUTO-CORRECTED: {error_msg}{C.RESET}")
                        
                        shell_cmd = f"echo '{final_cmd}' | nc -w 1 {self.socket_host} {self.socket_port}"
                        readable = self.get_readable_action(final_cmd)
                        if reward_type == 'visible':
                            print(f"  {C.BOLD}{C.YELLOW}★ VISIBLE: {readable}{C.RESET}")
                        else:
                            print(f"  {C.BOLD}{C.GREEN}⚡ {readable}{C.RESET}")
                        try:
                            subprocess.run(shell_cmd, shell=True, timeout=5,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                            print(f"  {C.GREEN}✓ {final_cmd}{C.RESET}")
                            
                            # Issue #28: Auto-Arc Detection — close matching arc if visible reward
                            if reward_type == 'visible' and not arc_closed_name:
                                self._auto_close_arc_for_reward(final_cmd)
                                
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
                            # Issue #25 — Drought Breaker: force heuristic reward if drought is critical
                            if self.ev_drought_count >= self.DROUGHT_BREAKER_THRESHOLD:
                                heuristic_cmd = self._get_heuristic_reward(event_type)
                                if heuristic_cmd:
                                    print(f"  {C.BOLD}{C.MAGENTA}🔄 DROUGHT BREAKER: Agent said none, forcing heuristic reward{C.RESET}")
                                    shell_cmd = f"echo '{heuristic_cmd}' | nc -w 1 {self.socket_host} {self.socket_port}"
                                    readable = self.get_readable_action(heuristic_cmd)
                                    print(f"  {C.BOLD}{C.YELLOW}★ FORCED: {readable}{C.RESET}")
                                    try:
                                        subprocess.run(shell_cmd, shell=True, timeout=5,
                                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                                        print(f"  {C.GREEN}✓ {heuristic_cmd}{C.RESET}")
                                        # Reset drought since we gave a visible reward
                                        self.ev_drought_count = 0
                                        self.session_visible_rewards += 1
                                        # Issue #28: Auto-Arc Detection for forced rewards
                                        self._auto_close_arc_for_reward(heuristic_cmd)
                                        # Log the forced decision
                                        self.decision_logger.log(
                                            event_type=event_type,
                                            action_cmd=f"FORCED:{heuristic_cmd}",
                                            reward_type='visible',
                                            drought=0,
                                            arcs_active=len(self._get_pending_arcs()),
                                            session_visible=self.session_visible_rewards,
                                            arc_closed=None,
                                            response_snippet="[DROUGHT BREAKER — heuristic reward forced]",
                                        )
                                    except subprocess.TimeoutExpired:
                                        print(f"  {C.YELLOW}✓ Sent{C.RESET}")
                                    except Exception as e:
                                        print(f"  {C.RED}✗ Heuristic failed: {e}{C.RESET}")
                                else:
                                    print(f"  {C.DIM}No action taken (drought: {self.ev_drought_count}, no heuristic available){C.RESET}")
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
        
        # Issue #40 — Auto-Arc Generation (Story Hook Detection)
        # Before building prompt, check if we need new arcs. If ARC LEDGER is nearly
        # empty, generate new story hooks from current team state. This addresses the
        # root cause of 91% "none" rate: Maren has nothing to work toward.
        pending_arcs = self._get_pending_arcs_structured()
        if self.arc_generator.needs_new_arcs(pending_arcs):
            new_arcs = self.arc_generator.maybe_generate_arcs(
                pending_arcs=pending_arcs,
                party=party,
                player_profile=self.player_profile.profile,
                battle_history=self.battle_history,
            )
            if new_arcs:
                # Re-fetch arcs after generation
                pending_arcs = self._get_pending_arcs_structured()
        
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

        elif event_type == 'GRIND_SUMMARY':
            # Lightweight batch prompt — triggered after long stretch of routine events
            # or extended silence (AgentConductor-inspired: dynamic event batching)
            skipped_count = ctx.get('skipped_count', len(self.skipped_events))
            elapsed_min = ctx.get('elapsed_minutes', 0)
            reason = ctx.get('reason', 'batch')

            prompt += f"=== GRIND SUMMARY ===\n"
            if reason == 'timeout':
                prompt += f"It's been {elapsed_min:.0f} minutes since Maren last made a decision.\n"
            else:
                prompt += f"{skipped_count} routine events have passed since your last decision.\n"
            prompt += "The player has been grinding — wild battles, exploring, the usual.\n"
            prompt += "No single event was significant enough to trigger a decision on its own.\n\n"
            prompt += "Your job now:\n"
            prompt += "1. Check the ARC LEDGER below. Is there a payoff you've been deferring?\n"
            prompt += "2. Has enough grind happened that an encouragement is warranted?\n"
            prompt += "3. If nothing warrants action, that's OK — say OBSERVATION: Watching, and ACTION: none\n"
            prompt += "Keep it brief. This is a check-in, not a major event.\n"

        # Issue #32 — Response Format Compression (OPSDC + Reasoning Theater)
        # Research (arxiv 2603.05433, 2603.05488) shows reasoning models often produce
        # "performative" CoT that wastes 70-80% of tokens without changing the answer.
        # For low-uncertainty routine events, request abbreviated response format.
        event_uncertainty = self.score_event_uncertainty(event_type, ctx)
        if event_uncertainty < self.CONCISE_MODE_THRESHOLD and event_type not in ('GRIND_SUMMARY',):
            prompt += "\n⚡ CONCISE MODE — This is a routine event.\n"
            prompt += "Skip OBSERVATION/PATTERN/MEMORY. Just respond with:\n"
            prompt += "  ACTION: <GM.xxx> or ACTION: none\n"
            prompt += "If something surprising happened, escalate with full format instead.\n"
        
        # Add accumulated skipped events as context
        if self.skipped_events:
            prompt += f"\n=== SINCE LAST UPDATE ({len(self.skipped_events)} routine events) ===\n"
            for event in self.skipped_events:
                prompt += f"• {event.get('summary', event.get('type'))}\n"
            prompt += "\n"
            # Clear after including
            self.skipped_events = []
        
        # Add session history context if available (Issue #14: KLong-inspired compression)
        if self.session_persistent:
            # Inject compressed summaries first (older history)
            if self.compressed_summaries:
                prompt += f"\n=== COMPRESSED HISTORY ({len(self.compressed_summaries)} summaries) ===\n"
                for i, summary in enumerate(self.compressed_summaries[-3:], 1):  # Last 3 summaries
                    prompt += f"[Summary {i}] {summary.get('covers', '?')} | {summary.get('summary', '')}\n"
                    if summary.get('key_decisions'):
                        prompt += f"  Key actions: {', '.join(summary['key_decisions'][:3])}\n"
                    if summary.get('arcs'):
                        prompt += f"  Arcs: {', '.join(summary['arcs'])}\n"

            # Then inject recent history
            # Issue #26 — Context Pollution Fix (MIT arxiv 2602.24287)
            # Research shows removing prior assistant responses can HELP by avoiding
            # "context pollution" where models over-condition on previous mistakes.
            # Instead of injecting truncated responses, show only event type + action taken.
            if self.session_history:
                recent_count = min(10, len(self.session_history))
                prompt += f"\n=== RECENT SESSION ({recent_count} events) ===\n"
                for entry in self.session_history[-10:]:
                    event_type_str = entry.get('event_type', 'unknown')
                    # Extract just the action from the response, not the full text
                    response = entry.get('response', '')
                    action = 'none'
                    for line in response.split('\n'):
                        if line.strip().startswith('ACTION:'):
                            action = line.split('ACTION:', 1)[1].strip()[:50]
                            break
                    prompt += f"• {event_type_str} → {action}\n"
                prompt += "Focus on current event. Don't repeat past decisions.\n"
        
        # === MAREN IMPACT SYSTEM ===

        # Issue #30 — Instruction Fade-Out Prevention (OPENDEV paper, arxiv 2603.05344)
        # Research shows agents drift from instructions over time. Counter with periodic
        # system reminders that restate core purpose. Triggered when:
        # 1. Drought is high (player hasn't felt Maren)
        # 2. Consecutive "none" responses indicate drift
        # 3. Enough events have passed since the last reminder
        should_remind = (
            self.ev_drought_count >= 5 and
            self.consecutive_none_count >= 4 and
            self.events_since_system_reminder >= self.SYSTEM_REMINDER_INTERVAL
        )
        if should_remind:
            pending_arcs = self._get_pending_arcs()
            arc_count = len(pending_arcs)
            prompt += f"\n{'='*56}\n"
            prompt += "=== SYSTEM REMINDER — INSTRUCTION FADE-OUT DETECTED ===\n"
            prompt += f"{'='*56}\n"
            prompt += "You are MAREN, the invisible Game Master for Pokemon Emerald.\n"
            prompt += "\n"
            prompt += "YOUR CORE PURPOSE:\n"
            prompt += "Make the game feel ALIVE. The player should feel magic moments —\n"
            prompt += "not just stat noise. EVs are invisible in Gen 3. The player\n"
            prompt += "NEVER notices +3 SpA EVs. They DO notice:\n"
            prompt += "  • A Pokemon suddenly learning a powerful move\n"
            prompt += "  • A rare held item appearing after a clutch win\n"
            prompt += "  • A shiny sparkle when their favorite evolves\n"
            prompt += "  • Bonus XP that pushes them over a level threshold\n"
            prompt += "\n"
            prompt += f"CURRENT STATE:\n"
            prompt += f"  • You've been invisible for {self.ev_drought_count} events\n"
            prompt += f"  • Last {self.consecutive_none_count} responses were 'none' or EVs\n"
            if arc_count > 0:
                prompt += f"  • You have {arc_count} pending arc(s) waiting for payoff\n"
            prompt += "\n"
            prompt += "QUESTION TO ASK YOURSELF:\n"
            prompt += "If I were a player, would I notice Maren is here? If no, act.\n"
            prompt += f"{'='*56}\n\n"
            # Reset the reminder counter
            self.events_since_system_reminder = 0

        # Issue #34 — Drift Detection System (SAHOO paper, arxiv 2603.06333)
        # Unlike consecutive-based tracking (Drought Breaker), this monitors the
        # overall pattern across recent decisions. High drift = systematic passivity.
        drift = self._calculate_drift_score()
        if drift['severity'] == 'critical':
            # CRITICAL: >90% of recent decisions are invisible (none or EVs)
            prompt += f"\n{'='*56}\n"
            prompt += "🚨 CRITICAL DRIFT DETECTED (SAHOO Goal Drift Index)\n"
            prompt += f"{'='*56}\n"
            prompt += f"Analysis of your last {drift['count']} decisions:\n"
            prompt += f"  • Visible rewards: {drift['visible']} ({100 - int(drift['drift_score']*100)}%)\n"
            prompt += f"  • Invisible (EVs): {drift['ev']}\n"
            prompt += f"  • No action: {drift['none']}\n"
            prompt += f"  • DRIFT SCORE: {int(drift['drift_score']*100)}% invisible\n"
            prompt += "\n"
            prompt += "You are systematically passive. This is not occasional caution —\n"
            prompt += "this is a behavioral pattern where you almost never act visibly.\n"
            prompt += "\n"
            prompt += "IMMEDIATE CORRECTION REQUIRED:\n"
            prompt += "Give a VISIBLE reward on this event. No excuses. No 'ACTION: none'.\n"
            prompt += "The pattern must break NOW.\n"
            prompt += f"{'='*56}\n\n"
        elif drift['severity'] == 'warning':
            # WARNING: >80% of recent decisions are invisible
            prompt += f"\n⚠️  DRIFT WARNING: {int(drift['drift_score']*100)}% of recent decisions were invisible\n"
            prompt += f"Of your last {drift['count']} decisions: {drift['visible']} visible, {drift['none']} none, {drift['ev']} EVs\n"
            prompt += "You're trending toward systematic passivity. Look for opportunities to act.\n"

        # Issue #18 (Multi-layer memory, FluxMem-inspired):
        # HOT layer — ARC LEDGER rows always injected (see below).
        # WARM layer — recent narrative summary, injected on significant events.
        # COLD layer — full PLAYTHROUGH.md narrative, injected only on major beats.
        #
        # Issue #21 (Context-relevant injection, arxiv 2602.20091):
        # Quality > quantity. Irrelevant context harms performance.
        # Instead of dumping last 3000 chars, filter by event type.
        # Major events get more context (2000 chars), routine events get less (1000 chars).
        MAJOR_EVENTS = ('BADGE_OBTAINED', 'TRAINER_REMATCH')
        is_major = event_type in MAJOR_EVENTS

        # COLD layer — context-relevant narrative filtered by event type
        # Major events get 2000 chars, routine battle/catch events get 1000 chars
        # GRIND_SUMMARY gets minimal context (arc ledger is enough)
        if event_type != 'GRIND_SUMMARY':
            max_chars = 2000 if is_major else 1000
            relevant_narrative = self._get_relevant_narrative(event_type, max_chars=max_chars)
            if relevant_narrative:
                label = "major event — full context" if is_major else "filtered by event type"
                prompt += f"\n=== NARRATIVE HISTORY ({label}) ===\n{relevant_narrative}\n"

        # Issue #33 — Quality-Aware Arc Prompting (A-MAC-inspired, arxiv 2603.05549)
        # For high-uncertainty events, proactively suggest arc opportunities
        # "Content type prior is the most influential factor" — A-MAC paper
        proactive_arcs = self._get_proactive_arc_suggestions(event_type, ctx)
        if proactive_arcs:
            prompt += f"\n{proactive_arcs}\n"

        # HOT layer — Inject pending arc payoffs (things Maren has promised in PLAYTHROUGH.md)
        # (Passive listing — always shown, supplements proactive suggestions for high-uncertainty events)
        pending_arcs = self._get_pending_arcs()
        if pending_arcs and not proactive_arcs:
            # Only show passive list if we didn't already show proactive suggestions
            prompt += f"\n=== PENDING ARC PAYOFFS (you promised these in PLAYTHROUGH.md) ===\n"
            for arc in pending_arcs:
                prompt += f"• {arc}\n"
            prompt += "\nIf this event creates an opportunity to deliver a payoff, DO IT. Don't defer again.\n"
            # Issue #17 — Arc delivery confirmation instruction
            prompt += ("When you deliver a promised arc, include this tag in your response:\n"
                       "  ARC_CLOSED: <exact arc name from ledger>\n"
                       "The daemon will automatically mark it DELIVERED in PLAYTHROUGH.md.\n")
        
        # Reward drought warning — escalate to visible if Maren has been invisible too long
        # Issue #25 — Drought Breaker (Evaluating Stochasticity, arxiv 2602.23271)
        if self.ev_drought_count >= self.DROUGHT_BREAKER_THRESHOLD:
            # CRITICAL — at this level, the daemon will force a heuristic reward if you say "none"
            prompt += f"\n🚨 CRITICAL DROUGHT: {self.ev_drought_count} consecutive invisible actions!\n"
            prompt += "The player has not felt Maren's presence in over a dozen events.\n"
            prompt += "⚠️  IF YOU SAY 'ACTION: none', the daemon will apply a HEURISTIC REWARD automatically.\n"
            prompt += "You MUST give a visible reward NOW. Options:\n"
            prompt += "  - GM.teachMove(slot, moveId, moveSlot) — learn a useful move\n"
            prompt += "  - GM.giveItem(slot, itemId) — give a held item\n"
            prompt += "  - GM.addExperience(slot, amount) — bonus XP for MVP\n"
            prompt += "Pick something meaningful. The drought MUST break.\n"
        elif self.ev_drought_count >= self.DROUGHT_WARNING_THRESHOLD:
            # Strong warning — getting close to forced intervention
            prompt += f"\n⚠️  HIGH DROUGHT WARNING: {self.ev_drought_count} consecutive invisible rewards!\n"
            prompt += f"The player hasn't noticed Maren in {self.ev_drought_count} events.\n"
            prompt += "You're close to automatic intervention. Give a VISIBLE reward:\n"
            prompt += "  teachMove, giveItem, setShiny, or addExperience (>100).\n"
            prompt += "EVs are invisible in Gen 3. The game needs to feel alive NOW.\n"
        elif self.ev_drought_count >= 3:
            prompt += f"\n⚠️  IMPACT WARNING: {self.ev_drought_count} consecutive invisible rewards (EVs/none).\n"
            prompt += f"The player hasn't noticed Maren in {self.ev_drought_count} events.\n"
            prompt += "If this event scores 4+ on the checklist, use a VISIBLE reward: teachMove, giveItem, or setShiny.\n"
            prompt += "EVs alone are not enough here. The game needs to feel alive.\n"
        
        # Session reward summary (occasional reminder of what's been given)
        if self.session_visible_rewards == 0 and len(self.reward_history) >= 5:
            prompt += "\n📊 SESSION NOTE: No visible rewards given yet this session. The player hasn't felt Maren.\n"

        # Issue #19 — Player Attribute Profile (EXACT-inspired inference-time personalization)
        # Inject behavioral profile so Maren can tailor rewards to who this player actually is.
        profile_block = self.player_profile.get_context_block()
        if profile_block:
            prompt += f"\n{profile_block}\n"

        # Issue #20 — Decision Library retrieval (MAS-on-the-Fly, phase 2)
        # Only activates after MIN_ENTRIES_FOR_RETRIEVAL decisions are logged.
        past_decisions = self.decision_logger.get_recent_patterns(event_type=event_type)
        if past_decisions:
            prompt += f"\n{past_decisions}\n"

        # Issue #37 — Trajectory Learning (IBM arxiv 2603.10600-inspired)
        # Extracts strategic insights from past decisions and injects as learned strategies.
        # Activates after MIN_ENTRIES decisions logged. Caches analysis for 1 hour.
        strategies_block = self.trajectory_learner.get_strategies_block(current_event_type=event_type)
        if strategies_block:
            prompt += f"\n{strategies_block}\n"

        # Issue #38 — Skill Extraction (XSkill-inspired, arxiv 2603.12056)
        # Extracts reusable procedural "skills" from successful decision patterns.
        # Skills are task-level abstractions (vs experiences which are action-level).
        # Uses current prompt context to match relevant skills.
        skills_block = self.skill_extractor.get_applicable_skills(
            event_type=event_type,
            context_snippet=prompt[-500:] if len(prompt) > 500 else prompt  # Recent context for matching
        )
        if skills_block:
            prompt += f"\n{skills_block}\n"

        # Issue #23 — Learning Directives ("Tell Me What To Learn", arxiv 2602.23201)
        # Inject configurable focus areas to guide what Maren pays attention to.
        directives_block = self.learning_directives.get_context_block()
        if directives_block:
            prompt += f"\n{directives_block}\n"

        # Issue #39 — Self-Verification Prompt (Cross-Context Review, arxiv 2603.12123)
        # Research finding: "LLMs catch more errors when explicitly verifying decisions"
        # (28.6% F1 vs 24.6% for same-session review, p=0.008)
        # Applied: For high-stakes moments, inject verification checklist.
        # This forces explicit reasoning before acting, catching decision errors.
        is_high_stakes = self._is_high_stakes_decision(event_type, pending_arcs, drift)
        if is_high_stakes:
            prompt += "\n=== DECISION VERIFICATION (Cross-Context Review) ===\n"
            prompt += "HIGH-STAKES MOMENT DETECTED. Before acting, verify:\n"
            prompt += "\n"
            prompt += "1. VISIBILITY CHECK:\n"
            prompt += "   □ Is my planned reward VISIBLE to the player?\n"
            prompt += "   • VISIBLE: teachMove, giveItem, setShiny, addExperience (>100)\n"
            prompt += "   • INVISIBLE: addEVs, setFriendship — player never sees these\n"
            prompt += "\n"
            prompt += "2. ARC ALIGNMENT:\n"
            prompt += "   □ Does this reward match a pending arc in the ARC LEDGER?\n"
            prompt += "   □ If closing an arc, include: ARC_CLOSED: <arc name>\n"
            prompt += "\n"
            prompt += "3. PLAYER IMPACT:\n"
            prompt += "   □ Will the player pause and go 'wait, how did that happen?'\n"
            prompt += "   □ Will this make the game feel alive, not just technically correct?\n"
            prompt += "\n"
            prompt += "If ANY check fails, reconsider your decision.\n"
            prompt += "=== END VERIFICATION ===\n"

        return prompt

    def _is_high_stakes_decision(self, event_type: str, pending_arcs: list, drift: dict) -> bool:
        """
        Determine if the current decision context is high-stakes.
        
        Issue #39 — Cross-Context Review (arxiv 2603.12123)
        Research shows explicit verification catches 16% more errors.
        We trigger verification for:
        - High drought (player hasn't felt Maren)
        - IMMEDIATE arcs pending
        - Trainer rematches (significant battles)
        - Drift severity warning or critical
        """
        # Drought approaching forced intervention
        if self.ev_drought_count >= 6:
            return True
        
        # IMMEDIATE arc waiting — this is a critical payoff opportunity
        if pending_arcs:
            for arc in pending_arcs:
                if 'IMMEDIATE' in arc.upper():
                    return True
        
        # Trainer rematch or major battle
        if hasattr(self, 'battle_buffer') and self.battle_buffer:
            for entry in self.battle_buffer:
                if entry.get('is_rematch') or entry.get('is_trainer'):
                    return True
        
        # Drift severity is elevated
        if drift.get('severity') in ('warning', 'critical'):
            return True
        
        return False
    
    def process_event(self, data: dict):
        """Process event from mGBA"""
        event_type = data.get('event_type', 'unknown')
        self.current_state = data  # Track for helpers
        
        # Dump state on meaningful events (not periodic polling)
        if event_type in ('battle_start', 'battle_end', 'level_up', 'move_learned', 
                          'item_obtained', 'pokemon_caught', 'evolution',
                          'dialogue', 'map_change'):
            self.write_state_dump(data)
        
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

            # Issue #19 — Update player profile
            self.player_profile.update_battle(
                outcome=outcome_name,
                party=party,
                was_close=(avg_hp < 0.25),
                is_trainer=any(e.get('is_trainer') for e in self.battle_buffer if e.get('event') == 'START'),
            )

            # Issue #29 — Track battle lead for contextual auto-arc detection
            # When visible bag items (GM.give) are given, we can infer the target Pokemon
            # from the lead of the most recent battle.
            if party and len(party) > 0 and outcome == 1:  # Only on wins
                lead_species = party[0].get('species', 0)
                self.last_battle_lead = self.get_species_name(lead_species)
                self.last_battle_lead_time = time.time()

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

            # Issue #14: Compress session history at badge milestones
            try:
                badge_int = int(badge_count) if isinstance(badge_count, str) else badge_count
                if badge_int > self.last_badge_count and len(self.session_history) >= 10:
                    self._compress_session_history(trigger=f'badge_{badge_int}')
                    self.last_badge_count = badge_int
            except (ValueError, TypeError):
                pass

            # Disabled: badge detection is unreliable, agent gets context from battles anyway
            # self.prompt_agent_async('BADGE_OBTAINED', {'state': data})
        
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
            # Issue #19 — Update player profile
            self.player_profile.update_caught(species_id=species, species_name=pokemon_name)
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
            # Issue #19 — Update player profile
            self.player_profile.update_move_mastery(move_id=move_id, count=count, move_name=move_name)
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

                # ── GRIND_SUMMARY check (AgentConductor-inspired — issue #15) ──
                # Trigger a lightweight batch prompt if:
                #   (a) N skipped events have accumulated, OR
                #   (b) GRIND_TIMEOUT_SEC have elapsed since last agent invocation
                # Only when agent is idle and game is connected.
                if not self.agent_busy and self.skipped_events:
                    now = time.time()
                    elapsed = now - self.last_agent_invoke_time
                    batch_full = len(self.skipped_events) >= self.GRIND_BATCH_SIZE
                    timed_out  = elapsed >= self.GRIND_TIMEOUT_SEC

                    if batch_full or timed_out:
                        reason = 'batch' if batch_full else 'timeout'
                        elapsed_min = elapsed / 60
                        C = Colors
                        self.log(
                            f"{C.DIM}⏱ GRIND_SUMMARY ({reason}, "
                            f"{len(self.skipped_events)} skipped, "
                            f"{elapsed_min:.1f}min since last invoke){C.RESET}"
                        )
                        self.prompt_agent_async('GRIND_SUMMARY', {
                            'state': self.current_state,
                            'skipped_count': len(self.skipped_events),
                            'elapsed_minutes': elapsed_min,
                            'reason': reason,
                        })

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
