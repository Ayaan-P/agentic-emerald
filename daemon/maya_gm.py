#!/usr/bin/env python3
"""
Maya's GM Daemon v2 - Event-driven, non-blocking
Sends game events to the emerald-gm agent for GM decisions
Now with Dytto context injection for better narrative decisions!
"""
import socket
import json
import time
import select
import subprocess
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

# Config
SOCKET_HOST = "172.28.208.1"  # Windows host from WSL
SOCKET_PORT = 8888
EVENTS_DIR = Path("/home/ayaan/projects/agentic-emerald/agent/state")
EVENTS_FILE = EVENTS_DIR / "maya_events.jsonl"
SESSION_FILE = EVENTS_DIR / "gm_session_id.txt"
PLAYTHROUGH_FILE = Path("/home/ayaan/projects/agentic-emerald/agent/memory/PLAYTHROUGH.md")
DYTTO_CONTEXT_SCRIPT = Path("/home/ayaan/.claude/lib/dytto-context.sh")
SPECIES_NAMES_FILE = Path(__file__).parent / "emerald_species.json"

# Load species names from Emerald internal species IDs
def load_species_names():
    """Load species names from Emerald internal ID mapping"""
    names = {}
    
    try:
        with open(SPECIES_NAMES_FILE, 'r') as f:
            data = json.load(f)
            
        species = data.get('species', {})
        
        # Build lookup: internal ID -> name
        for species_id, name in species.items():
            names[int(species_id)] = name
            
        print(f"[SPECIES] Loaded {len(names)} Pokemon from {SPECIES_NAMES_FILE}")
        
    except FileNotFoundError:
        print(f"[SPECIES] Warning: {SPECIES_NAMES_FILE} not found, using fallback")
    except json.JSONDecodeError as e:
        print(f"[SPECIES] Warning: JSON parse error: {e}")
    except Exception as e:
        print(f"[SPECIES] Warning: Failed to load species names: {e}")
    
    return names

SPECIES_NAMES = load_species_names()

# Move name lookup for tracking (common early moves)
MOVE_NAMES = {
    10: "Scratch", 13: "Razor Wind", 14: "Swords Dance", 15: "Cut",
    33: "Tackle", 45: "Growl", 52: "Ember", 53: "Flamethrower",
    64: "Peck", 83: "Fire Spin", 88: "Rock Throw", 89: "Earthquake",
    116: "Focus Energy", 163: "Slash", 172: "Flame Wheel",
    224: "Mega Kick", 241: "Sunny Day", 249: "Rock Smash",
    257: "Heat Wave", 299: "Blaze Kick", 315: "Overheat",
    394: "Flare Blitz",
}
# Agent figures out upgrades using its Pokemon knowledge - no hardcoded paths

class MayaGM:
    # ANSI colors for terminal output
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # Colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    
    # Background
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    
    def __init__(self):
        self.sock = None
        self.connected = False
        self.battles_won = 0
        self.pokemon_caught = 0
        self.last_event_time = 0
        self.pending_events = []
        self.agent_busy = False
        
        # Load or create session ID for conversation continuity
        self.session_id = self._load_or_create_session()
        
        # State tracking
        self.current_state = {}
        self.last_map = None
        self.last_in_battle = False
        
        # Battle history for pattern recognition
        self.battle_history = []  # Last N battles: {enemy, outcome, hp_after, was_close}
        self.MAX_BATTLE_HISTORY = 10
        self.session_start = time.time()
        self.close_calls = 0  # Battles won with <25% HP
        self.total_damage_taken = 0
        
        # Move usage tracking
        self.move_usage = {}  # {moveId: count}
        
        # Battle event buffer (batch and send at battle end)
        self.battle_buffer = []
        self.in_battle = False
        self.battle_start_time = None
        self.battle_start_hp = {}  # {slot: hp} at battle start
        self.battle_start_levels = {}  # {slot: level} at battle start
        
        # Dytto context cache (refreshed periodically)
        self.dytto_context = None
        self.dytto_context_time = 0
        self.DYTTO_CACHE_TTL = 300  # Refresh every 5 minutes
        
        # Ensure directories exist
        EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    
    def _load_or_create_session(self):
        """Load session ID from file for continuity, or create new one"""
        try:
            if SESSION_FILE.exists():
                session_id = SESSION_FILE.read_text().strip()
                if session_id:
                    print(f"[SESSION] Resuming session: {session_id}")
                    return session_id
        except Exception as e:
            print(f"[SESSION] Warning: Could not load session: {e}")
        
        # Create new session
        session_id = f"gm-{uuid.uuid4().hex[:8]}"
        try:
            SESSION_FILE.write_text(session_id)
            print(f"[SESSION] Created new session: {session_id}")
        except Exception as e:
            print(f"[SESSION] Warning: Could not save session: {e}")
        
        return session_id
    
    def reset_session(self):
        """Force a new session (for testing or when starting fresh playthrough)"""
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
        self.session_id = self._load_or_create_session()
        print(f"[SESSION] Reset to new session: {self.session_id}")
    
    def get_dytto_context(self):
        """Fetch user context from Dytto API for better narrative decisions"""
        now = time.time()
        
        # Return cached context if fresh
        if self.dytto_context and (now - self.dytto_context_time) < self.DYTTO_CACHE_TTL:
            return self.dytto_context
        
        try:
            result = subprocess.run(
                ["bash", str(DYTTO_CONTEXT_SCRIPT), "summary"],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0 and result.stdout.strip():
                # Parse the JSON response
                context_data = json.loads(result.stdout.strip())
                
                # Extract relevant info for GM
                summary = context_data.get("summary", {})
                mood = summary.get("current_mood", "unknown")
                energy = summary.get("energy_level", "unknown")
                focus = summary.get("current_focus", "unknown")
                patterns = summary.get("recent_patterns", [])
                
                self.dytto_context = {
                    "mood": mood,
                    "energy": energy,
                    "focus": focus,
                    "patterns": patterns[:3] if patterns else []  # Top 3 patterns
                }
                self.dytto_context_time = now
                self.log(f"{self.DIM}Dytto: {mood}, {energy}{self.RESET}")
                return self.dytto_context
                
        except subprocess.TimeoutExpired:
            pass  # Silent timeout
        except json.JSONDecodeError:
            pass  # Silent parse error
        except Exception:
            pass  # Silent error
        
        # Return stale cache or empty if no cache
        return self.dytto_context or {"mood": "unknown", "energy": "unknown", "focus": "unknown", "patterns": []}
        
    def log(self, msg, style=None):
        ts = datetime.now().strftime("%H:%M:%S")
        ts_str = f"{self.DIM}{ts}{self.RESET}"
        print(f"{ts_str}  {msg}")
    
    def get_readable_action(self, action_cmd):
        """Convert GM command to human-readable description"""
        import re
        
        # EV stat names to readable
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
                # EVs to stat point conversion (roughly 4 EVs = 1 stat point at lvl 100)
                return f"{pokemon} gains +{amount} {stat_name} training"
            
            # GM.healParty()
            if 'GM.healParty()' in action_cmd:
                return "Party fully restored!"
            
            # GM.teachMove(slot, moveId, moveSlot)
            match = re.search(r'GM\.teachMove\((\d+),\s*(\d+)', action_cmd)
            if match:
                slot, move_id = match.groups()
                pokemon = self.get_party_pokemon_name(int(slot))
                move_name = MOVE_NAMES.get(int(move_id), f"new move")
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
    
    def get_party_pokemon_name(self, slot):
        """Get Pokemon name from current party by slot"""
        try:
            party = self.current_state.get('party', [])
            if 0 <= slot < len(party):
                species = party[slot].get('species', 0)
                return self.get_species_name(species)
        except:
            pass
        return f"Pokemon #{slot}"
        
    def connect(self):
        """Connect to mGBA socket server"""
        try:
            self.sock = socket.socket()
            self.sock.settimeout(5)
            self.sock.connect((SOCKET_HOST, SOCKET_PORT))
            self.sock.setblocking(False)
            self.connected = True
            self.log(f"{self.GREEN}● Connected{self.RESET} to mGBA on {self.CYAN}{SOCKET_HOST}:{SOCKET_PORT}{self.RESET}")
            return True
        except Exception as e:
            self.log(f"{self.RED}✗ Connection failed:{self.RESET} {e}")
            self.connected = False
            return False
            
    def send_command(self, lua_code):
        """Send Lua command to mGBA"""
        if not self.connected or not self.sock:
            return None
        try:
            self.sock.send((lua_code + "\n").encode())
            time.sleep(0.05)  # Brief wait for response
            try:
                resp = self.sock.recv(4096).decode()
                return json.loads(resp.strip())
            except:
                return None
        except Exception as e:
            self.log(f"{self.YELLOW}Command error: {e}{self.RESET}")
            return None

    def get_species_name(self, species_id):
        """Get species name from national dex ID.
        
        The Lua script already handles the decomp offset by subtracting it.
        So species_id from Lua IS the national dex number (1-386).
        Just look it up directly.
        """
        if species_id <= 0:
            return "???"
        
        # Direct lookup - Lua already converted to national dex
        if species_id in SPECIES_NAMES:
            return SPECIES_NAMES[species_id]
        
        return f"Pokemon #{species_id}"

    def format_party(self, party):
        """Format party for display"""
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
        
    def write_event(self, event_type, data):
        """Write event to file for debugging"""
        event = {
            "time": datetime.now().isoformat(),
            "type": event_type,
            **data
        }
        with open(EVENTS_FILE, 'a') as f:
            f.write(json.dumps(event) + "\n")
            
    def prompt_agent_async(self, event_type, context):
        """Prompt the emerald-gm agent in a background thread"""
        if self.agent_busy:
            self.log(f"{self.DIM}Queueing: {event_type}{self.RESET}")
            self.pending_events.append((event_type, context))
            return
            
        def run_agent():
            self.agent_busy = True
            response_file = EVENTS_DIR / "gm_response.txt"
            try:
                prompt = self.build_prompt(event_type, context)
                self.log(f"{self.MAGENTA}▲ THINKING...{self.RESET}  {self.DIM}{event_type}{self.RESET}")
                
                # Clear previous response
                if response_file.exists():
                    response_file.unlink()
                
                # Run the agent with fresh session (forces new system prompt)
                result = subprocess.run(
                    ["clawdbot", "agent", "--agent", "agentic-emerald", "--session-id", self.session_id, "--message", prompt],
                    capture_output=True, text=True, timeout=60
                )
                
                if result.returncode == 0:
                    # Wait a moment for file write, then check
                    for _ in range(10):  # Try for up to 1 second
                        time.sleep(0.1)
                        if response_file.exists():
                            response_text = response_file.read_text().strip()
                            if response_text:
                                self.log(f"{self.GREEN}▼ AI RESPONSE{self.RESET}")
                                print(f"  {self.DIM}{'─' * 56}{self.RESET}")
                                action_cmd = None
                                for line in response_text.split('\n')[:10]:
                                    if line.strip():
                                        # Color-code different response types
                                        if line.startswith('OBSERVATION:'):
                                            label = f"{self.CYAN}OBS{self.RESET}"
                                            content = line.split(':', 1)[1].strip()
                                        elif line.startswith('PATTERN:'):
                                            label = f"{self.YELLOW}PTN{self.RESET}"
                                            content = line.split(':', 1)[1].strip()
                                        elif line.startswith('MEMORY:'):
                                            label = f"{self.MAGENTA}MEM{self.RESET}"
                                            content = line.split(':', 1)[1].strip()
                                        elif line.startswith('ACTION:'):
                                            label = f"{self.GREEN}ACT{self.RESET}"
                                            content = line.split(':', 1)[1].strip()
                                        else:
                                            label = f"{self.DIM}...{self.RESET}"
                                            content = line.strip()
                                        print(f"  {label}  {content}")
                                        # Extract ACTION line for execution
                                        if line.strip().startswith('ACTION:'):
                                            action_cmd = line.split('ACTION:', 1)[1].strip()
                                
                                print(f"  {self.DIM}{'─' * 56}{self.RESET}")
                                
                                # Execute the ACTION if it's a real command
                                if action_cmd and action_cmd.lower() != 'none':
                                    # Add nc timeout flag if missing
                                    if '| nc ' in action_cmd and ' -w ' not in action_cmd and ' -q ' not in action_cmd:
                                        action_cmd = action_cmd.replace('| nc ', '| nc -w 1 ')
                                    
                                    # Human-readable action description
                                    readable = self.get_readable_action(action_cmd)
                                    print(f"  {self.BOLD}{self.GREEN}⚡ {readable}{self.RESET}")
                                    
                                    try:
                                        # Suppress stdout (game server JSON spam), keep stderr for errors
                                        subprocess.run(action_cmd, shell=True, timeout=5, 
                                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                                        print(f"  {self.GREEN}✓ Complete{self.RESET}")
                                    except subprocess.TimeoutExpired:
                                        print(f"  {self.YELLOW}✓ Sent{self.RESET}")
                                    except Exception as e:
                                        print(f"  {self.RED}✗ Failed: {e}{self.RESET}")
                                else:
                                    print(f"  {self.DIM}No action taken{self.RESET}")
                                break
                    else:
                        self.log(f"{self.DIM}Agent completed{self.RESET}")
                else:
                    self.log(f"{self.RED}✗ Agent error{self.RESET}")
                    
            except subprocess.TimeoutExpired:
                self.log(f"{self.YELLOW}⏱ Agent timeout{self.RESET}")
            except Exception as e:
                self.log(f"{self.RED}✗ Agent error: {e}{self.RESET}")
            finally:
                self.agent_busy = False
                # Process queued events
                if self.pending_events:
                    next_event, next_ctx = self.pending_events.pop(0)
                    self.prompt_agent_async(next_event, next_ctx)
        
        thread = threading.Thread(target=run_agent, daemon=True)
        thread.start()
        
    def build_prompt(self, event_type, ctx):
        """Build a context-rich prompt for the GM agent"""
        state = ctx.get('state', {})
        
        # Calculate party health average
        party = state.get('party', [])
        if party:
            total_hp_pct = sum(
                (p.get('current_hp', 0) / max(p.get('max_hp', 1), 1)) * 100 
                for p in party
            )
            avg_hp = int(total_hp_pct / len(party))
        else:
            avg_hp = 100
        
        party_str = self.format_party(party)
        session_mins = int((time.time() - self.session_start) / 60)
        
        # Build prompt with context
        prompt = f"EVENT: {event_type}\n"
        prompt += f"Party: {party_str}\n"
        prompt += f"Party HP: {avg_hp}% avg\n"
        prompt += f"Session: {session_mins} mins | Badges: {state.get('badge_count', 0)}\n"
        prompt += f"Stats: {self.battles_won} wins, {self.pokemon_caught} caught, {self.close_calls} close calls\n"
        
        # Recent battle history for pattern recognition
        if self.battle_history:
            recent = self.battle_history[-3:]  # Last 3 battles
            history_str = ", ".join([
                f"{b['enemy']}({'close' if b['was_close'] else 'clean'})" 
                for b in recent
            ])
            prompt += f"Recent: {history_str}\n"
        
        # Event-specific details
        if event_type == 'BATTLE_SUMMARY':
            buffer = ctx.get('buffer', [])
            outcome = ctx.get('outcome', 'unknown')
            
            prompt += f"=== BATTLE COMPLETE ===\n"
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
            
            # Add all battle dialogue - the actual game text
            battle_dialogue = ctx.get('battle_dialogue', [])
            if battle_dialogue:
                prompt += "\n=== BATTLE TEXT (what the game showed) ===\n"
                for text in battle_dialogue[-30:]:  # Last 30 messages
                    prompt += f"• {text}\n"
            
            # Add battle play-by-play from Lua battle log
            battle_log = ctx.get('battle_log', [])
            if battle_log:
                prompt += "\n=== DAMAGE LOG ===\n"
                for entry in battle_log[-20:]:  # Last 20 events max
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
                
        elif event_type == 'POKEMON_CAUGHT':
            caught = ctx.get('caught_species', 0)
            prompt += f"CAUGHT: {self.get_species_name(caught)}\n"
            
        elif event_type == 'MOVE_MASTERY':
            move_id = ctx.get('move_id', 0)
            move_name = ctx.get('move_name', 'Unknown')
            count = ctx.get('count', 0)
            prompt += f"🎯 PATTERN: Player has used {move_name} (id:{move_id}) {count} times!\n"
            prompt += "You know Pokemon — if this move has a natural evolution/upgrade, consider rewarding mastery.\n"
            prompt += "Use GM.teachMove(slot, moveId, moveSlot) to teach new moves. Check GM_INSTRUCTIONS.md for move IDs.\n"
            
        elif event_type == 'EXPLORATION_SUMMARY':
            state = ctx.get('state', {})
            summary = ctx.get('summary', '')
            trigger = ctx.get('trigger', 'unknown')
            
            prompt += f"=== EXPLORATION UPDATE (trigger: {trigger}) ===\n"
            prompt += f"Summary: {summary}\n"
            
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
                # Include actual dialogue text if available
                dialogues = state.get('dialogueTexts', [])
                for i, text in enumerate(dialogues[:5]):  # Limit to 5 dialogues
                    prompt += f"  Dialogue {i+1}: \"{text[:100]}{'...' if len(text) > 100 else ''}\"\n"
            level_ups = state.get('levelUps', [])
            for lu in level_ups:
                species_name = self.get_species_name(lu.get('species', 0))
                prompt += f"⬆️ {species_name}: Level {lu.get('oldLevel')} → {lu.get('newLevel')}\n"

        return prompt

    def process_event(self, data):
        """Process an event from mGBA"""
        event_type = data.get('event_type', 'unknown')
        self.current_state = data
        
        # Track state changes
        in_battle = data.get('in_battle', False)
        current_map = (data.get('map_group'), data.get('map_num'))
        
        # Log significant events
        if event_type == 'battle_start':
            enemy = data.get('enemy') or {}
            enemy_name = self.get_species_name(enemy.get('species', 0))
            enemy_level = enemy.get('level', '?')
            battle_info = data.get('battleInfo', {})
            enemy_party = data.get('enemyParty', [])
            is_trainer = battle_info.get('is_trainer', False)
            self.current_enemy = f"{enemy_name} L{enemy_level}"  # Track for history
            battle_type = "TRAINER" if is_trainer else "WILD"
            
            # Start battle buffering
            self.in_battle = True
            self.battle_start_time = time.time()
            self.battle_buffer = [{
                'event': 'START',
                'type': battle_type,
                'enemy': self.current_enemy,
                'enemy_party': [f"{self.get_species_name(p.get('species',0))} L{p.get('level','?')}" for p in enemy_party] if enemy_party else None,
            }]
            
            # Record starting HP
            party = data.get('party', [])
            self.battle_start_hp = {i: p.get('current_hp', 0) for i, p in enumerate(party)}
            self.battle_start_levels = {i: p.get('level', 0) for i, p in enumerate(party)}
            
            if is_trainer and enemy_party:
                self.log(f"{self.BOLD}{self.RED}⚔ BATTLE{self.RESET}  {self.YELLOW}{battle_type}{self.RESET} vs {self.WHITE}{self.BOLD}{enemy_name}{self.RESET} L{enemy_level} {self.DIM}(party of {len(enemy_party)}){self.RESET}")
            else:
                self.log(f"{self.BOLD}{self.RED}⚔ BATTLE{self.RESET}  {self.YELLOW}{battle_type}{self.RESET} vs {self.WHITE}{self.BOLD}{enemy_name}{self.RESET} L{enemy_level}")
            
            self.write_event('BATTLE_START', {'enemy': enemy, 'is_trainer': is_trainer, 'enemy_party': enemy_party})
            
        elif event_type == 'battle_end':
            # Use the outcome from event data, not from state!
            outcome = data.get('outcome', 0)
            outcome_name = data.get('outcomeName', 'unknown')
            
            # Check for level ups - strong indicator of winning
            party = data.get('party', [])
            level_ups = []
            for i, p in enumerate(party):
                start_level = self.battle_start_levels.get(i, p.get('level', 0))
                current_level = p.get('level', 0)
                if current_level > start_level:
                    name = self.get_species_name(p.get('species', 0))
                    level_ups.append(f"{name} L{start_level}→{current_level}")
            
            # If we detected level ups but outcome says lost/ran/unknown, override to won
            # Level ups mean XP was gained = enemy defeated = win
            if level_ups and outcome in [0, 2, 4]:  # unknown, lost, or ran
                outcome = 1
                outcome_name = "won"
            
            # Color-code outcome
            if outcome == 1:
                outcome_color = self.GREEN
            elif outcome == 2:
                outcome_color = self.RED  
            else:
                outcome_color = self.YELLOW
            self.log(f"{self.BOLD}🏁 END{self.RESET}  {outcome_color}{outcome_name.upper()}{self.RESET}")
            self.write_event('BATTLE_END', {'outcome': outcome, 'outcome_name': outcome_name})
            
            # Calculate HP status for history
            party = data.get('party', [])
            if party:
                avg_hp = sum(p.get('current_hp', 0) / max(p.get('max_hp', 1), 1) for p in party) / len(party)
                was_close = avg_hp < 0.25
            else:
                avg_hp = 1.0
                was_close = False
            
            # Calculate damage taken during battle
            damage_taken = {}
            for i, p in enumerate(party):
                start_hp = self.battle_start_hp.get(i, p.get('max_hp', 0))
                current_hp = p.get('current_hp', 0)
                if start_hp > current_hp:
                    name = self.get_species_name(p.get('species', 0))
                    damage_taken[name] = start_hp - current_hp
            
            # Add end event to buffer
            battle_duration = int(time.time() - (self.battle_start_time or time.time()))
            self.battle_buffer.append({
                'event': 'END',
                'outcome': outcome_name,
                'duration_sec': battle_duration,
                'hp_after': int(avg_hp * 100),
                'was_close': was_close,
                'damage_taken': damage_taken,
            })
            
            # Record to battle history
            battle_record = {
                'enemy': getattr(self, 'current_enemy', 'Unknown'),
                'outcome': outcome_name,
                'hp_after': int(avg_hp * 100),
                'was_close': was_close
            }
            self.battle_history.append(battle_record)
            if len(self.battle_history) > self.MAX_BATTLE_HISTORY:
                self.battle_history.pop(0)
            
            if was_close and outcome == 1:
                self.close_calls += 1
            
            # Send batched battle summary to agent
            # Include outcome 0 (unknown) and 4 (fled) so agent can narrate all battle endings
            if outcome in [0, 1, 2, 4, 7]:  # Unknown, Won, Lost, Fled, or Caught
                if outcome == 1:
                    self.battles_won += 1
                elif outcome == 4:
                    self.log(f"{self.DIM}← Fled{self.RESET}")
                elif outcome == 7:
                    self.pokemon_caught += 1
                    caught_species = party[-1].get('species', 0) if party else 0
                    pokemon_name = self.get_species_name(caught_species)
                    self.battle_buffer.append({'event': 'CAUGHT', 'pokemon': pokemon_name})
                    print(f"\n  {self.BOLD}{self.MAGENTA}◆ CAUGHT: {pokemon_name}! ◆{self.RESET}\n")
                
                # Send the full battle buffer to agent
                party = data.get('party', [])
                
                self.prompt_agent_async('BATTLE_SUMMARY', {
                    'state': data,
                    'buffer': self.battle_buffer,
                    'outcome': outcome_name,
                    'battle_log': data.get('battleLog', []),
                    'battle_dialogue': data.get('battleDialogue', []),  # All game text
                })
            
            # Clear battle state
            self.in_battle = False
            self.battle_buffer = []
                
        elif event_type == 'map_transition':
            from_map = data.get('from', '?')
            to_map = data.get('to', '?')
            self.log(f"{self.BLUE}▸ MAP{self.RESET}  {self.DIM}{from_map}{self.RESET} → {self.WHITE}{to_map}{self.RESET}")
            self.write_event('MAP_CHANGE', {'from': from_map, 'to': to_map})
            
        elif event_type == 'exploration_summary':
            trigger = data.get('trigger', '?')
            from_map = data.get('fromMap', '?')
            items = data.get('itemsGained', 0)
            money = data.get('moneyChange', 0)
            dialogues = data.get('dialogueCount', 0)
            level_ups = data.get('levelUps', [])
            
            # Only log/prompt if something interesting happened
            parts = []
            if items > 0:
                parts.append(f"+{items} items")
            if money > 0:
                parts.append(f"+${money}")
            elif money < 0:
                parts.append(f"-${abs(money)}")
            if dialogues > 0:
                parts.append(f"{dialogues} NPCs")
            for lu in level_ups:
                species_name = self.get_species_name(lu.get('species', 0))
                parts.append(f"{species_name} L{lu.get('oldLevel')}→{lu.get('newLevel')}")
            
            if parts:
                summary = " │ ".join(parts)
                self.log(f"{self.BLUE}▸ EXPLORE{self.RESET}  {summary}")
                self.write_event('EXPLORATION_SUMMARY', data)
                
                # Prompt agent with exploration summary
                self.prompt_agent_async('EXPLORATION_SUMMARY', {
                    'state': data,
                    'summary': summary,
                    'trigger': trigger,
                })
            
        elif event_type == 'pokemon_caught':
            species = data.get('species', 0)
            pokemon_name = self.get_species_name(species)
            print(f"\n  {self.BOLD}{self.MAGENTA}{'◆' * 30}{self.RESET}")
            print(f"  {self.BOLD}{self.MAGENTA}◆  CAUGHT: {pokemon_name}!  ◆{self.RESET}")
            print(f"  {self.BOLD}{self.MAGENTA}{'◆' * 30}{self.RESET}\n")
            
        elif event_type == 'badge_obtained':
            badge_count = data.get('badgeCount', '?')
            print(f"\n  {self.BOLD}{self.YELLOW}{'★' * 40}{self.RESET}")
            print(f"  {self.BOLD}{self.YELLOW}★  BADGE OBTAINED!  ★  Total: {badge_count}  ★{self.RESET}")
            print(f"  {self.BOLD}{self.YELLOW}{'★' * 40}{self.RESET}\n")
            self.prompt_agent_async('BADGE_OBTAINED', {'state': data})
        
        elif event_type == 'move_mastery':
            move_id = data.get('moveId', 0)
            count = data.get('count', 0)
            move_name = MOVE_NAMES.get(move_id, f"Move #{move_id}")
            
            self.move_usage[move_id] = count
            self.log(f"{self.YELLOW}★ MASTERY{self.RESET}  {self.WHITE}{self.BOLD}{move_name}{self.RESET} used {count}x")
            
            # Prompt agent about the pattern — agent decides what to do
            self.prompt_agent_async('MOVE_MASTERY', {
                'state': data,
                'move_id': move_id,
                'move_name': move_name,
                'count': count,
            })
            
        elif event_type == 'item_pickup':
            gained = data.get('gained', 0)
            self.log(f"{self.GREEN}▸ ITEM{self.RESET}  +{gained}")
            
        elif event_type == 'party_changed':
            # Simple debounce: only log party every 30 seconds max
            now = time.time()
            if not hasattr(self, '_last_party_log'):
                self._last_party_log = 0
            
            if now - self._last_party_log < 30:
                return
            
            self._last_party_log = now
            party = data.get('party', [])
            
            # Format party with HP bars
            parts = []
            for p in party:
                name = self.get_species_name(p.get('species', 0))
                level = p.get('level', '?')
                hp = p.get('current_hp', 0)
                max_hp = p.get('max_hp', 1)
                hp_pct = hp / max(max_hp, 1)
                
                # Color based on HP
                if hp_pct > 0.5:
                    hp_color = self.GREEN
                elif hp_pct > 0.2:
                    hp_color = self.YELLOW
                elif hp_pct > 0:
                    hp_color = self.RED
                else:
                    hp_color = self.DIM
                
                parts.append(f"{name} {self.DIM}L{level}{self.RESET} {hp_color}{hp}/{max_hp}{self.RESET}")
            
            self.log(f"{self.CYAN}▸ PARTY{self.RESET}  {' │ '.join(parts)}")
            
        elif event_type == 'connected':
            self.log(f"{self.GREEN}● Ready{self.RESET}  {self.DIM}Game connected{self.RESET}")
            
        elif event_type == 'periodic_state':
            # Silent periodic updates - just update state
            pass
            
        self.last_in_battle = in_battle
        self.last_map = current_map

    def print_banner(self):
        """Print startup banner"""
        banner = f"""
{self.BOLD}{self.MAGENTA}╔══════════════════════════════════════════════════════════╗
║  {self.CYAN}▄▀█ █▀▀ █▀▀ █▄ █ ▀█▀ █ █▀▀   █▀▀ █▀▄▀█ █▀▀ █▀█ ▄▀█ █   █▀▄{self.MAGENTA}  ║
║  {self.CYAN}█▀█ █▄█ ██▄ █ ▀█  █  █ █▄▄   ██▄ █ ▀ █ ██▄ █▀▄ █▀█ █▄▄ █▄▀{self.MAGENTA}  ║
║                                                            ║
║  {self.WHITE}AI Game Master • Narrative-Driven Pokemon{self.MAGENTA}                 ║
╚══════════════════════════════════════════════════════════╝{self.RESET}
"""
        print(banner)
    
    def run(self):
        """Main loop"""
        self.print_banner()
        
        while True:
            # Connect if needed
            if not self.connected:
                if not self.connect():
                    time.sleep(5)
                    continue
                    
            # Read from socket
            try:
                ready = select.select([self.sock], [], [], 0.1)
                if ready[0]:
                    data = self.sock.recv(16384).decode()
                    for line in data.strip().split('\n'):
                        if line:
                            try:
                                event = json.loads(line)
                                self.process_event(event)
                            except json.JSONDecodeError:
                                pass  # Silent JSON errors
            except BlockingIOError:
                pass
            except ConnectionResetError:
                self.log(f"{self.YELLOW}○ Reconnecting...{self.RESET}")
                self.connected = False
                time.sleep(2)
            except KeyboardInterrupt:
                print(f"\n{self.DIM}Shutting down...{self.RESET}")
                break
            except Exception as e:
                self.log(f"{self.RED}✗ Error: {e}{self.RESET}")
                self.connected = False
                time.sleep(2)


if __name__ == "__main__":
    gm = MayaGM()
    gm.run()
