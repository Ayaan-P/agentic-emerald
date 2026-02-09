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


# Common move names for logging
MOVE_NAMES = {
    10: "Scratch", 13: "Razor Wind", 14: "Swords Dance", 15: "Cut",
    33: "Tackle", 45: "Growl", 52: "Ember", 53: "Flamethrower",
    64: "Peck", 83: "Fire Spin", 88: "Rock Throw", 89: "Earthquake",
    116: "Focus Energy", 163: "Slash", 172: "Flame Wheel",
}


class PokemonGM:
    def __init__(self, config: dict, base_path: Path):
        self.config = config
        self.base_path = base_path
        
        # Connection settings
        emu_config = config.get('emulator', {})
        self.socket_host = emu_config.get('host', '127.0.0.1')
        self.socket_port = emu_config.get('port', 8888)
        
        # Paths
        paths = config.get('paths', {})
        self.state_dir = base_path / paths.get('state_dir', './state')
        self.memory_dir = base_path / paths.get('memory_dir', './memory')
        self.events_file = self.state_dir / 'events.jsonl'
        self.response_file = self.state_dir / 'gm_response.txt'
        
        # Species names
        species_file = base_path / paths.get('species_file', './data/emerald_species.json')
        self.species_names = load_species_names(species_file)
        
        # Agent settings
        agent_config = config.get('agent', {})
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
        
        # Stats
        self.battles_won = 0
        self.pokemon_caught = 0
        self.close_calls = 0
        self.session_start = time.time()
        
        # Battle tracking
        self.battle_history = []
        self.battle_buffer = []
        self.in_battle = False
        self.battle_start_time = None
        self.battle_start_hp = {}
        self.battle_start_levels = {}
        
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
        print(f"[{ts}] {msg}")
    
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
    
    def connect(self) -> bool:
        try:
            self.sock = socket.socket()
            self.sock.settimeout(5)
            self.sock.connect((self.socket_host, self.socket_port))
            self.sock.setblocking(False)
            self.connected = True
            self.log(f"🎮 Connected to mGBA on {self.socket_host}:{self.socket_port}")
            return True
        except Exception as e:
            self.log(f"❌ Connection failed: {e}")
            self.connected = False
            return False
    
    def write_event(self, event_type: str, data: dict):
        event = {"time": datetime.now().isoformat(), "type": event_type, **data}
        with open(self.events_file, 'a') as f:
            f.write(json.dumps(event) + "\n")
    
    def prompt_agent_async(self, event_type: str, context: dict):
        """Send event to AI agent in background thread"""
        if self.agent_busy:
            self.log(f"⏳ Agent busy, queueing: {event_type}")
            self.pending_events.append((event_type, context))
            return
        
        def run_agent():
            self.agent_busy = True
            try:
                prompt = self.build_prompt(event_type, context)
                self.log(f"📨 → Agent: {event_type}")
                
                if self.agent_mode == 'direct':
                    response_text = self._call_anthropic_direct(prompt)
                elif self.agent_mode == 'claude':
                    response_text = self._call_claude_cli(prompt)
                elif self.agent_mode == 'codex':
                    response_text = self._call_codex_cli(prompt)
                else:  # clawdbot (default)
                    response_text = self._call_clawdbot(prompt)
                
                if response_text:
                    self.log(f"✅ Agent responded to {event_type}")
                    # Save to session history if persistent
                    self._add_to_session_history(event_type, prompt, response_text)
                    
                    action_cmd = None
                    for line in response_text.split('\n')[:10]:
                        if line.strip():
                            self.log(f"   🤖 {line[:120]}")
                            if line.strip().startswith('ACTION:'):
                                action_cmd = line.split('ACTION:', 1)[1].strip()
                    
                    # Execute action if present
                    if action_cmd and action_cmd.lower() != 'none':
                        # Add nc timeout flag if missing
                        if '| nc ' in action_cmd and ' -w ' not in action_cmd:
                            action_cmd = action_cmd.replace('| nc ', '| nc -w 1 ')
                        self.log(f"   ⚡ Executing: {action_cmd[:80]}")
                        try:
                            subprocess.run(action_cmd, shell=True, timeout=5)
                            self.log(f"   ✅ Action complete")
                        except subprocess.TimeoutExpired:
                            self.log(f"   ⚠️ Action sent (nc timeout normal)")
                        except Exception as e:
                            self.log(f"   ❌ Action failed: {e}")
                    
            except Exception as e:
                self.log(f"❌ Agent error: {e}")
            finally:
                self.agent_busy = False
                if self.pending_events:
                    next_event, next_ctx = self.pending_events.pop(0)
                    self.prompt_agent_async(next_event, next_ctx)
        
        threading.Thread(target=run_agent, daemon=True).start()
    
    def _call_clawdbot(self, prompt: str) -> str:
        """Call agent via Clawdbot CLI"""
        # Clear previous response
        if self.response_file.exists():
            self.response_file.unlink()
        
        result = subprocess.run(
            ["clawdbot", "agent", "--agent", self.agent_id,
             "--session-id", self.session_id, "--message", prompt],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode == 0:
            # Check for response file
            for _ in range(10):
                time.sleep(0.1)
                if self.response_file.exists():
                    return self.response_file.read_text().strip()
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
            ["claude", "-p", full_prompt, "--no-markdown"],
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
        
        # Event-specific details
        if event_type == 'BATTLE_SUMMARY':
            buffer = ctx.get('buffer', [])
            prompt += "=== BATTLE COMPLETE ===\n"
            for event in buffer:
                if event.get('event') == 'START':
                    prompt += f"Started: {event.get('type')} vs {event.get('enemy')}\n"
                elif event.get('event') == 'END':
                    prompt += f"Duration: {event.get('duration_sec')}s, HP: {event.get('hp_after')}%\n"
                    if event.get('was_close'):
                        prompt += "⚠️ CLOSE CALL!\n"
            
            battle_dialogue = ctx.get('battle_dialogue', [])
            if battle_dialogue:
                prompt += "\n=== BATTLE TEXT ===\n"
                for text in battle_dialogue[-30:]:
                    prompt += f"• {text}\n"
        
        elif event_type == 'EXPLORATION_SUMMARY':
            summary = ctx.get('summary', '')
            prompt += f"=== EXPLORATION ===\n{summary}\n"
        
        # Add session history context if available
        if self.session_persistent and self.session_history:
            prompt += f"\n=== SESSION HISTORY ({len(self.session_history)} previous events) ===\n"
            # Include last 5 interactions to keep context window manageable
            for entry in self.session_history[-5:]:
                prompt += f"• [{entry.get('event_type', 'unknown')}] {entry.get('response', '')[:100]}\n"
            prompt += "\nRemember the context from these previous events when making decisions.\n"
        
        return prompt
    
    def process_event(self, data: dict):
        """Process event from mGBA"""
        event_type = data.get('event_type', 'unknown')
        
        if event_type == 'battle_start':
            enemy = data.get('enemy', {})
            enemy_name = self.get_species_name(enemy.get('species', 0))
            battle_info = data.get('battleInfo', {})
            is_trainer = battle_info.get('is_trainer', False)
            is_double = battle_info.get('is_double', False)
            
            self.in_battle = True
            self.battle_start_time = time.time()
            
            battle_type = 'TRAINER' if is_trainer else 'WILD'
            if is_double:
                battle_type += ' (DOUBLE)'
            
            self.battle_buffer = [{
                'event': 'START',
                'type': battle_type,
                'enemy': f"{enemy_name} L{enemy.get('level', '?')}",
                'is_double': is_double,
                'is_trainer': is_trainer
            }]
            
            party = data.get('party', [])
            self.battle_start_hp = {i: p.get('current_hp', 0) for i, p in enumerate(party)}
            self.battle_start_levels = {i: p.get('level', 0) for i, p in enumerate(party)}
            
            battle_log = f"⚔️ BATTLE START: vs {enemy_name}"
            if is_double:
                battle_log += " [DOUBLE BATTLE]"
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
            self.battle_buffer.append({
                'event': 'END',
                'outcome': outcome_name,
                'duration_sec': duration,
                'hp_after': int(avg_hp * 100),
                'was_close': avg_hp < 0.25
            })
            
            self.log(f"🏁 BATTLE END: {outcome_name}")
            
            if outcome == 1:
                self.battles_won += 1
            if avg_hp < 0.25 and outcome == 1:
                self.close_calls += 1
            
            # Send to agent
            self.prompt_agent_async('BATTLE_SUMMARY', {
                'state': data,
                'buffer': self.battle_buffer,
                'outcome': outcome_name,
                'battle_dialogue': data.get('battleDialogue', [])
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
                summary = ", ".join(parts)
                self.log(f"📊 EXPLORATION: {summary}")
                self.prompt_agent_async('EXPLORATION_SUMMARY', {
                    'state': data,
                    'summary': summary
                })
        
        elif event_type == 'badge_obtained':
            self.log(f"🏅 BADGE OBTAINED!")
            self.prompt_agent_async('BADGE_OBTAINED', {'state': data})
        
        elif event_type == 'party_changed':
            self.log(f"📋 Party: {self.format_party(data.get('party', []))}")
        
        elif event_type == 'connected':
            self.log(f"✅ Server ready")
    
    def run(self):
        """Main event loop"""
        self.log("🎮 Agentic Emerald Daemon starting...")
        
        while True:
            if not self.connected:
                if not self.connect():
                    time.sleep(5)
                    continue
            
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
    parser = argparse.ArgumentParser(description="Agentic Emerald Daemon")
    parser.add_argument('-c', '--config', default='config.yaml',
                        help='Path to config file (default: config.yaml)')
    args = parser.parse_args()
    
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    
    config = load_config(config_path)
    base_path = config_path.parent
    
    gm = PokemonGM(config, base_path)
    gm.run()


if __name__ == "__main__":
    main()
