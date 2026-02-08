# Agentic Emerald

An AI Game Master for Pokemon Emerald that watches your playthrough and subtly rewards story moments — making the game feel like it *knows* you.

## What It Does

The GM observes your gameplay through the emulator and responds with invisible interventions:

- **Win a tough battle?** Your Pokemon quietly gains EVs
- **Same Pokemon leading for 20 battles?** Loyalty bonus incoming
- **Caught a rare Pokemon?** Better IVs than usual
- **Lost to the gym twice?** Your team "trains harder" overnight

You never see the GM. But you *feel* that something is different.

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
3. **AI agent** interprets events as story beats and decides on interventions
4. **Commands** are sent back to the Lua script to modify game state

## Supported Games

- ✅ Pokemon Emerald (primary)
- 🚧 Pokemon Red/Blue (Gen 1) — partial support

## Quick Start

### Prerequisites

- [mGBA](https://mgba.io/) emulator with Lua scripting enabled
- Python 3.10+
- An Anthropic API key (Claude)

**Agent modes (pick one):**
- **Claude CLI** (recommended): Uses your Claude Code/Max subscription — no API key needed
- **Codex CLI**: Uses your OpenAI/Codex subscription
- **Direct**: Calls Anthropic API with your API key
- **Clawdbot**: Uses [Clawdbot](https://github.com/clawdbot/clawdbot) for advanced features

### Installation

```bash
# Clone the repo
git clone https://github.com/yourusername/agentic-emerald.git
cd agentic-emerald

# Install Python dependencies
pip install -r requirements.txt

# Copy and edit config
cp config.example.yaml config.yaml
# Edit config.yaml with your paths and settings
```

### Setup mGBA

1. Open mGBA → Tools → Scripting
2. Load `lua/game_master_v2.lua`
3. The script will start a socket server for the daemon

### Run

```bash
# Start the daemon (after mGBA is running with Lua script)
python daemon/agentic_emerald.py

# Start playing — the GM is watching
```

## Configuration

Edit `config.yaml`:

```yaml
# Connection to mGBA Lua server
emulator:
  host: "127.0.0.1"  # Use your host IP if running in WSL
  port: 8888

# Paths
paths:
  state_dir: "./state"
  memory_dir: "./memory"

# Agent settings
agent:
  # "claude" = Claude CLI (uses Max/Pro subscription) ← recommended
  # "codex" = Codex CLI (uses OpenAI subscription)  
  # "direct" = Anthropic API (requires api_key)
  # "clawdbot" = Clawdbot CLI (advanced)
  mode: "claude"
  workspace: "./agent"

# Optional: Real-world context (requires Dytto)
dytto:
  enabled: false
  api_key: ""
```

## The GM Philosophy

The AI isn't adjusting difficulty — it's **telling your story**.

From `GM_NARRATIVE.md`:

> Every time you see an event, ask:
> **"What just happened in this person's story, and how do I honor it?"**
>
> Not "should I intervene?" — you almost always should, even small.
> Not "is the player struggling?" — that's game balance thinking.
> Instead: What's the *moment*?

### Story Beats

| Event | GM Response |
|-------|-------------|
| Pokemon faints so another can win | The survivor gains EVs — sacrifice honored |
| Same type used for 10+ battles | Type specialist emerging — themed item appears |
| Caught a 4% encounter rate Pokemon | Better IVs — "you earned this" |
| Lost to gym twice | Party trains overnight — bonus EVs |
| Level up after close battle | Extra EV boost — growth through adversity |

## Project Structure

```
agentic-emerald/
├── daemon/
│   └── agentic_emerald.py # Main daemon
├── lua/
│   ├── gm_server.lua      # Socket server + event emitter
│   ├── gm_tools.lua       # GM intervention functions
│   ├── state.lua          # Game state reading
│   └── events.lua         # Event detection
├── agent/
│   ├── AGENTS.md          # Agent instructions
│   ├── GM_NARRATIVE.md    # Storytelling philosophy
│   └── GM_INSTRUCTIONS.md # Technical command reference
├── memory/
│   └── PLAYTHROUGH.md     # Persistent story memory
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

## Optional: Dytto Integration

With [Dytto](https://dytto.app), the GM can access real-world context:

- Had a rough day? The game is gentler
- Energetic mood? Rivals fight harder
- Late night session? Ghost types feel more present

Enable in `config.yaml` and add your Dytto API key.

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

Built by [@ayaan](https://twitter.com/ayaan).

The GM philosophy was developed through extensive playtesting of "what would make Pokemon feel alive?"

Optionally integrates with [Clawdbot](https://clawdbot.com) for advanced agent management.
