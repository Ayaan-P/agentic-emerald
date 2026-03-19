#!/usr/bin/env python3
"""
Issue #42 — Health Check Tool for Agentic Emerald
Analyzes the current state of the daemon's memory and decision systems.

Run: python3 tools/health_check.py
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

# Colors for terminal output
class C:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

def print_header(title):
    print(f"\n{C.BOLD}{C.CYAN}=== {title} ==={C.RESET}")

def print_ok(msg):
    print(f"  {C.GREEN}✓{C.RESET} {msg}")

def print_warn(msg):
    print(f"  {C.YELLOW}⚠{C.RESET} {msg}")

def print_error(msg):
    print(f"  {C.RED}✗{C.RESET} {msg}")

def analyze_decisions(decisions_path):
    print_header("DECISION ANALYSIS")
    
    if not decisions_path.exists():
        print_warn("No decisions.jsonl found — no gameplay recorded yet")
        return
    
    with open(decisions_path) as f:
        decisions = [json.loads(line) for line in f]
    
    if not decisions:
        print_warn("decisions.jsonl is empty")
        return
    
    total = len(decisions)
    none_count = sum(1 for d in decisions if d['action'] == 'none')
    visible_count = sum(1 for d in decisions if d.get('reward_type') == 'visible')
    forced_count = sum(1 for d in decisions if d['action'].startswith('FORCED'))
    
    # Calculate rates
    none_rate = none_count / total * 100
    visible_rate = visible_count / total * 100
    
    print(f"  Total decisions: {total}")
    print(f"  Visible rewards: {visible_count} ({visible_rate:.1f}%)")
    print(f"  Forced interventions: {forced_count}")
    print(f"  None rate: {none_rate:.1f}%")
    
    if none_rate > 90:
        print_warn(f"High passivity: {none_rate:.1f}% none rate")
    elif none_rate > 80:
        print_warn(f"Elevated passivity: {none_rate:.1f}% none rate")
    else:
        print_ok(f"Passivity within range: {none_rate:.1f}% none rate")
    
    # Analyze by event type
    from collections import Counter
    types = Counter(d['event_type'] for d in decisions)
    print(f"\n  By event type:")
    for t, c in types.most_common():
        t_none = sum(1 for d in decisions if d['event_type'] == t and d['action'] == 'none')
        t_rate = t_none / c * 100
        status = "⚠" if t_rate > 95 else "✓" if t_rate < 80 else "•"
        print(f"    {status} {t}: {c} events ({t_rate:.0f}% none)")
    
    # Drought analysis
    max_drought = max(d['drought'] for d in decisions)
    recent_30 = decisions[-30:] if len(decisions) >= 30 else decisions
    recent_none_rate = sum(1 for d in recent_30 if d['action'] == 'none') / len(recent_30) * 100
    
    print(f"\n  Max drought observed: {max_drought}")
    if max_drought > 20:
        print_warn(f"Very high max drought ({max_drought}) — Drought Breaker may not have been active")
    elif max_drought > 12:
        print_ok(f"Drought breaker active (max {max_drought})")
    
    print(f"  Recent 30 decisions none rate: {recent_none_rate:.1f}%")
    
    # Arc closures
    arc_closures = [d for d in decisions if d.get('arc_closed')]
    print(f"\n  Arc closures: {len(arc_closures)}")
    for d in arc_closures:
        print(f"    • {d['arc_closed']}")

def analyze_arcs(playthrough_path):
    print_header("ARC LEDGER STATUS")
    
    if not playthrough_path.exists():
        print_warn("No PLAYTHROUGH.md found")
        return
    
    with open(playthrough_path) as f:
        content = f.read()
    
    if '## ARC LEDGER' not in content:
        print_warn("No ARC LEDGER section in PLAYTHROUGH.md")
        return
    
    # Parse arc table
    ledger_section = content.split('## ARC LEDGER')[1].split('##')[0]
    
    pending = re.findall(r'\| ([^|]+) \| ([^|]+) \| PENDING \| ([^|]+) \| ([^|]+) \|', ledger_section)
    immediate = re.findall(r'\| ([^|]+) \| ([^|]+) \| IMMEDIATE \| ([^|]+) \| ([^|]+) \|', ledger_section)
    delivered = re.findall(r'\| ([^|]+) \| ([^|]+) \| DELIVERED \| ([^|]+) \| ([^|]+) \|', ledger_section)
    
    print(f"  DELIVERED: {len(delivered)}")
    print(f"  PENDING: {len(pending)}")
    print(f"  IMMEDIATE: {len(immediate)}")
    
    if pending:
        print(f"\n  Active arcs:")
        for arc, pokemon, promise, priority in pending:
            print(f"    🟡 [{priority.strip()}] {arc.strip()} ({pokemon.strip()})")
            print(f"       {promise.strip()[:60]}...")
    
    if immediate:
        print(f"\n  IMMEDIATE arcs (needs closing!):")
        for arc, pokemon, promise, priority in immediate:
            print(f"    🔴 [{priority.strip()}] {arc.strip()} ({pokemon.strip()})")
    
    # Check if auto-arc generator should trigger
    high_pending = [a for a in pending if 'HIGH' in a[3]]
    if not high_pending:
        print_warn("No HIGH priority PENDING arcs — Auto-Arc Generator will trigger next session")
    else:
        print_ok(f"{len(high_pending)} HIGH priority PENDING arcs active")

def analyze_profile(profile_path):
    print_header("PLAYER PROFILE")
    
    if not profile_path.exists():
        print_warn("No player_profile.json found")
        return
    
    with open(profile_path) as f:
        profile = json.load(f)
    
    print(f"  Version: {profile.get('version', '?')}")
    print(f"  Last updated: {profile.get('updated_at', '?')[:19]}")
    
    trust = profile.get('pokemon_trust', {})
    if trust:
        print(f"\n  Pokemon Trust ({len(trust)} species):")
        # Sort by battles led
        sorted_trust = sorted(trust.items(), key=lambda x: x[1]['battles_led'], reverse=True)
        for pid, data in sorted_trust[:5]:
            name = data['name']
            led = data['battles_led']
            won = data['battles_won']
            win_rate = (won / led * 100) if led > 0 else 0
            print(f"    • {name}: {led} led, {won} won ({win_rate:.0f}%)")
    
    attrs = profile.get('attributes', {})
    if attrs:
        print(f"\n  Inferred attributes:")
        print(f"    Playstyle: {attrs.get('playstyle', '?')}")
        print(f"    Risk tolerance: {attrs.get('risk_tolerance', 0):.2f}")
        print(f"    Type specialization: {attrs.get('type_specialization', 'None')}")
        print(f"    Comeback ratio: {attrs.get('comeback_ratio', 0):.2f}")

def analyze_session(session_path):
    print_header("SESSION STATE")
    
    if not session_path.exists():
        print_warn("No session.json found")
        return
    
    with open(session_path) as f:
        session = json.load(f)
    
    history = session.get('history', [])
    print(f"  History entries: {len(history)}")
    
    # Check for compression
    compressed = [h for h in history if h.get('type') == 'history_summary']
    print(f"  Compressed summaries: {len(compressed)}")
    
    if len(history) > 50 and not compressed:
        print_warn(f"Large history ({len(history)} entries) but no compression — may need restart")

def check_compression_status(decisions_path, compressed_path):
    print_header("MEMORY COMPRESSION")
    
    if not decisions_path.exists():
        print_warn("No decisions.jsonl to compress")
        return
    
    with open(decisions_path) as f:
        decisions = [json.loads(line) for line in f]
    
    if len(decisions) < 50:
        print_ok(f"Only {len(decisions)} decisions — no compression needed yet")
        return
    
    # Check age of oldest decision
    cutoff = datetime.now() - timedelta(days=7)
    cutoff_str = cutoff.isoformat()
    
    old = [d for d in decisions if d.get('ts', '') < cutoff_str]
    recent = [d for d in decisions if d.get('ts', '') >= cutoff_str]
    
    print(f"  Total decisions: {len(decisions)}")
    print(f"  Older than 7 days: {len(old)}")
    print(f"  Recent (last 7 days): {len(recent)}")
    
    if compressed_path.exists():
        with open(compressed_path) as f:
            summaries = [json.loads(line) for line in f]
        print_ok(f"Compressed file exists with {len(summaries)} summaries")
    else:
        if len(old) >= 50:
            print_warn(f"{len(old)} old decisions ready for compression — will run on next daemon start")
        else:
            print_ok("No compression needed yet")

def generate_recommendations(base):
    """Generate actionable recommendations based on detected issues."""
    recommendations = []
    agent_state = base / 'agent' / 'state'
    agent_memory = base / 'agent' / 'memory'
    
    # Check decisions
    decisions_path = agent_state / 'decisions.jsonl'
    if decisions_path.exists():
        with open(decisions_path) as f:
            decisions = [json.loads(line) for line in f]
        
        if decisions:
            none_rate = sum(1 for d in decisions if d['action'] == 'none') / len(decisions) * 100
            max_drought = max(d['drought'] for d in decisions)
            
            # High passivity
            if none_rate > 85:
                recommendations.append({
                    'priority': 'HIGH',
                    'issue': f'High passivity ({none_rate:.0f}% none rate)',
                    'action': 'Start a gameplay session — Auto-Arc Generator will create new goals',
                    'auto': True
                })
            
            # Pre-feature drought data
            if max_drought > 20:
                recommendations.append({
                    'priority': 'LOW',
                    'issue': f'Historical high drought ({max_drought}) in older data',
                    'action': 'No action needed — Drought Breaker now caps at 12',
                    'auto': True
                })
    
    # Check arcs
    playthrough_path = agent_memory / 'PLAYTHROUGH.md'
    if playthrough_path.exists():
        with open(playthrough_path) as f:
            content = f.read()
        
        if '## ARC LEDGER' in content:
            ledger = content.split('## ARC LEDGER')[1].split('##')[0]
            pending_high = re.findall(r'\| ([^|]+) \| ([^|]+) \| PENDING \| ([^|]+) \| HIGH', ledger)
            immediate = re.findall(r'\| ([^|]+) \| ([^|]+) \| IMMEDIATE', ledger)
            
            if not pending_high and not immediate:
                recommendations.append({
                    'priority': 'MEDIUM',
                    'issue': 'No HIGH priority arcs pending',
                    'action': 'Play a battle — ArcGenerator will create new story hooks from team state',
                    'auto': True
                })
            
            if immediate:
                for arc in immediate:
                    recommendations.append({
                        'priority': 'HIGH',
                        'issue': f'IMMEDIATE arc waiting: {arc[0].strip()}',
                        'action': 'Arc should close on next relevant event',
                        'auto': True
                    })
    
    # Check compression status
    if decisions_path.exists():
        with open(decisions_path) as f:
            decisions = [json.loads(line) for line in f]
        
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        old_count = sum(1 for d in decisions if d.get('ts', '') < cutoff)
        
        if old_count >= 50:
            recommendations.append({
                'priority': 'LOW',
                'issue': f'{old_count} old decisions ready for compression',
                'action': 'Restart daemon — compression runs automatically on startup',
                'auto': True
            })
    
    # Check profile freshness
    profile_path = agent_state / 'player_profile.json'
    if profile_path.exists():
        with open(profile_path) as f:
            profile = json.load(f)
        
        updated = profile.get('updated_at', '')
        if updated:
            try:
                updated_dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                days_old = (datetime.now() - updated_dt.replace(tzinfo=None)).days
                if days_old > 7:
                    recommendations.append({
                        'priority': 'LOW',
                        'issue': f'Player profile is {days_old} days old',
                        'action': 'Profile auto-updates on gameplay — play to refresh',
                        'auto': True
                    })
            except:
                pass
    
    return recommendations

def print_recommendations(recommendations):
    """Print actionable recommendations."""
    if not recommendations:
        print_header("RECOMMENDATIONS")
        print_ok("No issues detected — system is healthy")
        return
    
    print_header("RECOMMENDATIONS")
    
    # Group by priority
    high = [r for r in recommendations if r['priority'] == 'HIGH']
    medium = [r for r in recommendations if r['priority'] == 'MEDIUM']
    low = [r for r in recommendations if r['priority'] == 'LOW']
    
    if high:
        print(f"\n  {C.RED}🔴 HIGH PRIORITY:{C.RESET}")
        for r in high:
            auto_tag = f" {C.GREEN}[auto]{C.RESET}" if r.get('auto') else ""
            print(f"    • {r['issue']}")
            print(f"      → {r['action']}{auto_tag}")
    
    if medium:
        print(f"\n  {C.YELLOW}🟡 MEDIUM:{C.RESET}")
        for r in medium:
            auto_tag = f" {C.GREEN}[auto]{C.RESET}" if r.get('auto') else ""
            print(f"    • {r['issue']}")
            print(f"      → {r['action']}{auto_tag}")
    
    if low:
        print(f"\n  {C.CYAN}🔵 LOW:{C.RESET}")
        for r in low:
            auto_tag = f" {C.GREEN}[auto]{C.RESET}" if r.get('auto') else ""
            print(f"    • {r['issue']}")
            print(f"      → {r['action']}{auto_tag}")
    
    # Summary
    auto_count = sum(1 for r in recommendations if r.get('auto'))
    if auto_count == len(recommendations):
        print(f"\n  {C.GREEN}All {auto_count} issues will auto-resolve on next gameplay/restart.{C.RESET}")

def main():
    print(f"\n{C.BOLD}AGENTIC EMERALD HEALTH CHECK{C.RESET}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Paths
    base = Path(__file__).parent.parent
    agent_state = base / 'agent' / 'state'
    agent_memory = base / 'agent' / 'memory'
    
    analyze_decisions(agent_state / 'decisions.jsonl')
    analyze_arcs(agent_memory / 'PLAYTHROUGH.md')
    analyze_profile(agent_state / 'player_profile.json')
    analyze_session(agent_state / 'session.json')
    check_compression_status(
        agent_state / 'decisions.jsonl',
        agent_state / 'decisions_compressed.jsonl'
    )
    
    # Generate and print recommendations
    recommendations = generate_recommendations(base)
    print_recommendations(recommendations)
    
    print(f"\n{C.BOLD}Health check complete.{C.RESET}\n")

if __name__ == '__main__':
    main()
