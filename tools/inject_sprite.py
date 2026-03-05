#!/usr/bin/env python3
"""
Inject sprite into running game via mGBA Lua socket.

Usage:
    python3 inject_sprite.py <species_id> <tiles.bin> <pal.bin> [host] [port]
    
Example:
    python3 inject_sprite.py 257 sprites/mega_blaziken_front.tiles.bin sprites/mega_blaziken_front.pal.bin
    
This sends the sprite data to the Lua script's cache, then it can be injected
when that species appears in battle.
"""

import socket
import base64
import sys
from pathlib import Path


def send_command(host: str, port: int, cmd: str, timeout: float = 2.0) -> str:
    """Send command to mGBA Lua socket"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        # Skip initial broadcast (connected event)
        try:
            _ = sock.recv(4096)  # Discard broadcast
        except socket.timeout:
            pass
        
        # Now send command
        sock.send((cmd + '\n').encode())
        
        # Get actual command response
        try:
            response = sock.recv(4096).decode()
            return response
        except socket.timeout:
            return ""
    finally:
        sock.close()


def cache_sprite(host: str, port: int, species_id: int, tiles_path: Path, pal_path: Path):
    """Send sprite data to Lua cache"""
    tiles_data = tiles_path.read_bytes()
    pal_data = pal_path.read_bytes()
    
    tiles_b64 = base64.b64encode(tiles_data).decode()
    pal_b64 = base64.b64encode(pal_data).decode()
    
    # Build Lua command
    cmd = f'GM.cacheSprite({species_id}, "{tiles_b64}", "{pal_b64}")'
    
    print(f"Caching sprite for species {species_id}...")
    print(f"  Tiles: {len(tiles_data)} bytes")
    print(f"  Palette: {len(pal_data)} bytes")
    
    response = send_command(host, port, cmd)
    print(f"Sent to {host}:{port}")
    if response:
        print(f"Response: {response}")
    
    return True


def inject_sprite(host: str, port: int, battler_slot: int, species_id: int):
    """Inject cached sprite into battler's VRAM"""
    cmd = f'GM.injectSprite({battler_slot}, {species_id})'
    print(f"Injecting species {species_id} into battler slot {battler_slot}...")
    response = send_command(host, port, cmd)
    if response:
        print(f"Response: {response}")
    return True


def debug_battler(host: str, port: int, battler_slot: int):
    """Get debug info about a battler's sprite"""
    cmd = f'GM.debugBattlerSprite({battler_slot})'
    response = send_command(host, port, cmd)
    print(response if response else "No response")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nCommands:")
        print("  cache <species_id> <tiles.bin> <pal.bin> [host] [port]")
        print("  inject <battler_slot> <species_id> [host] [port]")
        print("  debug <battler_slot> [host] [port]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    host = "127.0.0.1"
    port = 8888
    
    if cmd == "cache":
        if len(sys.argv) < 5:
            print("Usage: inject_sprite.py cache <species_id> <tiles.bin> <pal.bin> [host] [port]")
            sys.exit(1)
        species_id = int(sys.argv[2])
        tiles_path = Path(sys.argv[3])
        pal_path = Path(sys.argv[4])
        if len(sys.argv) > 5:
            host = sys.argv[5]
        if len(sys.argv) > 6:
            port = int(sys.argv[6])
        cache_sprite(host, port, species_id, tiles_path, pal_path)
        
    elif cmd == "inject":
        if len(sys.argv) < 4:
            print("Usage: inject_sprite.py inject <battler_slot> <species_id> [host] [port]")
            sys.exit(1)
        battler_slot = int(sys.argv[2])
        species_id = int(sys.argv[3])
        if len(sys.argv) > 4:
            host = sys.argv[4]
        if len(sys.argv) > 5:
            port = int(sys.argv[5])
        inject_sprite(host, port, battler_slot, species_id)
        
    elif cmd == "debug":
        if len(sys.argv) < 3:
            print("Usage: inject_sprite.py debug <battler_slot> [host] [port]")
            sys.exit(1)
        battler_slot = int(sys.argv[2])
        if len(sys.argv) > 3:
            host = sys.argv[3]
        if len(sys.argv) > 4:
            port = int(sys.argv[4])
        debug_battler(host, port, battler_slot)
        
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    main()
