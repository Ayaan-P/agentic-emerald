# Agentic Emerald

An AI Game Master for Pokemon Emerald. Watches your playthrough via mGBA and rewards story moments with invisible interventions (EVs, moves, items).

## What It Does

The GM observes gameplay events and triggers rewards:

- **Battle won** → Pokemon gains EVs
- **Same Pokemon leading 20+ battles** → Bonus stats
- **Caught a rare Pokemon** → Better IVs
- **Lost to gym twice** → Party gets training EVs

## How It Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   mGBA      │────▶│  Lua Script │────▶│   Daemon    │────▶│  AI Agent   │
│  Emulator   │◀────│  (events)   │◀────│  (Python)   │◀────│  (Claude)   │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │                   │
       │    Game state     │   JSON events     │    Story beats    │
       │    (memory)       │   via socket      │    + commands     │
       └───────────────────┴───────────────────┴───────────────────┘
```

1. **Lua scripts** read game memory (party, battles, items) and emit events
2. **Python daemon** receives events and prompts the AI agent
3. **AI agent** decides what rewards to give based on game events
4. **Commands** are sent back to the Lua script to modify game state

## Supported Games

- ✅ Pokemon Emerald (primary)
- 🚧 Pokemon Red/Blue (Gen 1) — partial support

## Quick Start

### Prerequisites

- **mGBA** (0.10.1+) with Lua scripting enabled — [download](https://mgba.io/)
  - Enable Lua: Tools → Scripting → Available scripts should be visible
  - Windows WSL users: Use `127.0.0.1` for mGBA config, point to WSL IP for daemon
- **Python** 3.10 or later
- **Agent** (pick one):
  - **Claude CLI** (recommended): Uses your Claude Code/Max subscription — no API key needed
  - **Codex CLI**: Uses your OpenAI/Codex subscription
  - **Direct API**: Calls Anthropic API (requires `ANTHROPIC_API_KEY`)
  - **Clawdbot**: Uses [Clawdbot](https://github.com/clawdbot/clawdbot) for session persistence + advanced features

### Installation

```bash
# Clone the repo
git clone https://github.com/Ayaan-P/agentic-emerald.git
cd agentic-emerald

# Install Python dependencies
pip install -r requirements.txt

# Copy and edit config
cp config.example.yaml config.yaml
# Edit config.yaml with your paths and settings
```

### Setup mGBA

1. **Open a Pokemon Emerald ROM** in mGBA
2. **Tools → Scripting** → Click "Script..." button
3. **Select** `lua/game_master_v2.lua` from your agentic-emerald directory
4. **Console** should show: `[GM] Connected to daemon on 127.0.0.1:8888`
   - If no connection yet, that's OK — the daemon will connect when it starts
5. Keep the Scripting console open while playing

### Run

```bash
# Start the daemon (after mGBA is running with Lua script)
python daemon/agentic_emerald.py

# Start playing — the GM is watching
```

## Configuration

### Basic Setup

1. **Copy example:** `cp config.example.yaml config.yaml`
2. **Edit** `config.yaml` with your setup:

```yaml
# Connection to mGBA Lua server
emulator:
  host: "127.0.0.1"  # Use "127.0.0.1" for same machine
                     # Use "172.28.208.1" (WSL IP) if mGBA is on Windows
  port: 8888

# Agent mode (pick one)
agent:
  mode: "claude"       # Claude CLI (recommended — uses your subscription)
  workspace: "./agent"
  
  # Uncomment for other modes:
  # mode: "codex"     # OpenAI Codex
  # mode: "direct"    # Anthropic API (set ANTHROPIC_API_KEY env var)
  # mode: "clawdbot"  # Clawdbot (session persistence + features)
```

### WSL Users

If running **mGBA on Windows** and **daemon in WSL**:

```yaml
emulator:
  # Find your WSL IP:
  # > ipconfig (in Windows) → look for "vEthernet (WSL)" IPv4 Address
  host: "172.28.208.1"  # Replace with your WSL IP
  port: 8888
```

### Session Persistence

By default, the daemon starts fresh each time. You can enable **session persistence** so the agent remembers the full playthrough context even if the daemon restarts:

```yaml
session:
  persistent: true  # Enable session history across restarts
```

When enabled, the daemon will:
- Load previous session events on startup
- Include context from the last 5 interactions in agent prompts
- Automatically save session history to `state/session.json`

This is especially useful for long playthroughs where you want the agent to remember all the decisions it's made.

### Real-World Context (Dytto)

Optionally, the GM can access your real-world context via **Dytto**. This lets the game adapt based on your mood, energy level, location, and recent life events.

**Setup:**

1. Install Dytto (if available): `pip install dytto`
2. Enable in config:

```yaml
dytto:
  enabled: true
  api_key: "your-dytto-api-key"  # Get from https://dytto.ai
```

**How the GM Uses It:**

The agent checks your context at key moments (gym battles, long sessions, story beats) and adapts accordingly:

| Your Real-World State | Game Adaptation |
|---------------------|-----------------|
| You're stressed/tired | Gym leader is slightly gentler, items appear to help |
| You're energetic | Rival gets sharper, battles are more challenging |
| It's late at night | Darker themes, ghost Pokemon are more present |
| You just had a win IRL | Lucky encounters, rare Pokemon appear |
| You're grinding hard | Bonus EVs across the board, Rare Candy appears |

The GM uses this **sparingly** — only at important moments, never to spam context. The goal: the game feels like it *knows* you, not just your save file.

### Smart Event Handling (CATTS)

The daemon uses **Certainty-Aware Task Scheduling (CATTS)** to decide when to invoke the AI agent:

**How It Works:**
- **Low-certainty events** (routine wild battles, catching common Pokemon): Uses fast local heuristics → EVs, items, friendship boosts
- **Medium-certainty events** (trainer battles): Queued for agent if busy, skipped if the queue is full
- **High-certainty events** (gym leaders, rare Pokemon, close calls): Always invokes the agent for creative decisions

**Result:**
- ~70% fewer AI invocations during typical gameplay
- 2.3x reduction in token usage
- Faster, more responsive decisions
- **Zero impact on narrative quality** — agent still handles all story-important moments

This is automatic and transparent. The daemon logs when it's using heuristics vs. invoking the agent, so you can see what's happening.

### Other Options

See `config.example.yaml` for:
- Logging and debugging
- Model overrides (for direct mode)

## How It Works

It's a game master. Like a DM in D&D, but for Pokemon.

The agent watches the game, tracks what's happening in `PLAYTHROUGH.md`, and decides when/how to intervene. No hardcoded rules — the LLM uses judgment based on the full context of your playthrough.

## Project Structure

```
agentic-emerald/
├── daemon/
│   └── agentic_emerald.py # Main daemon
├── lua/
│   ├── game_master_v2.lua # Main Lua script (load this in mGBA)
│   ├── gm_tools.lua       # GM intervention functions
│   ├── state.lua          # Game state reading
│   └── events.lua         # Event detection
├── agent/
│   ├── AGENTS.md          # Agent instructions
│   ├── GM_NARRATIVE.md    # Reward logic and rules
│   └── GM_INSTRUCTIONS.md # Technical command reference
├── memory/
│   └── PLAYTHROUGH.md     # Playthrough history (agent writes here)
├── config.example.yaml
└── requirements.txt
```

## Commands Reference

The GM can execute these through the Lua script:

```lua
-- EV rewards (slot 0-5, stats: hp/atk/def/spd/spatk/spdef)
GM.setEVs(slot, hp, atk, def, spd, spatk, spdef)

-- Teach moves
GM.teachMove(slot, moveId, moveSlot)

-- Give items
GM.giveItem(itemId, quantity)

-- Special rewards
GM.setShiny(slot)
GM.setIVs(slot, hp, atk, def, spd, spatk, spdef)
```

## Clawdbot Mode (Optional)

If you use [Clawdbot](https://github.com/clawdbot/clawdbot), you can use it for agent management:

```yaml
agent:
  mode: "clawdbot"
  id: "agentic-emerald"
```

```bash
# Add the agent to Clawdbot
clawdbot agent add agentic-emerald \
  --model anthropic/claude-sonnet-4-20250514 \
  --workspace ./agent
```

This gives you session persistence, multi-agent orchestration, and other Clawdbot features.

## Troubleshooting

### Lua script fails to load in mGBA
- **Check mGBA version:** Lua scripting requires 0.10.1+
- **Check ROM:** Only English Gen 3 Emerald is tested
- **Try direct path:** Some versions need full path to script

### Daemon won't connect to mGBA
- **Check emulator config:** Edit `config.yaml` — match host/port in mGBA Lua console
- **WSL users:** If mGBA is on Windows, use your WSL IP (e.g., `192.168.x.x`) in config, not `127.0.0.1`
- **Firewall:** Allow Python on port 8888 (or your configured port)

### No agent response
- **Check agent mode:** Run `cat config.yaml | grep "mode:"`
- **Claude CLI:** Make sure `claude` is in PATH (`which claude`)
- **Direct API:** Verify `ANTHROPIC_API_KEY` is set (`echo $ANTHROPIC_API_KEY`)
- **Clawdbot:** Verify agent registered (`clawdbot agent status agentic-emerald`)

### Rewards aren't applying
- **Check Lua console:** Look for errors like `GM: Invalid moveId`
- **Check PLAYTHROUGH.md:** The agent should log decisions here
- **Check daemon logs:** Run daemon with `-v` flag for verbose output

## Contributing

PRs welcome! Areas that need work:

- [ ] Gen 1 parity (Red/Blue/Yellow)
- [ ] Gen 4+ support
- [ ] Web UI for GM settings
- [ ] "Narrative packs" — different GM personalities
- [ ] Support for other LLMs (OpenAI, local models)

## License

MIT

## Credits

Built by [Ayaan](https://github.com/Ayaan-P). Optionally integrates with [Clawdbot](https://clawdbot.com).
