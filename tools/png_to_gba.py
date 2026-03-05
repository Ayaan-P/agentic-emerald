#!/usr/bin/env python3
"""
PNG to GBA Sprite Converter

Converts a 64x64 indexed PNG + JASC-PAL palette to GBA-compatible formats:
- Tile data: 4bpp, 8x8 tiles (2048 bytes for 64x64 sprite)
- Palette data: RGB555, 16 colors (32 bytes)

Usage:
    python3 png_to_gba.py sprites/mega_blaziken_front.png sprites/mega_blaziken.pal
    
Outputs:
    sprites/mega_blaziken_front.tiles.bin  (tile data for VRAM)
    sprites/mega_blaziken_front.pal.bin    (palette data)
"""

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("PIL required. Install with: pip install Pillow")
    sys.exit(1)


def parse_jasc_pal(pal_path: Path) -> list[tuple[int, int, int]]:
    """Parse JASC-PAL format palette file"""
    lines = pal_path.read_text().strip().split('\n')
    
    if lines[0] != 'JASC-PAL':
        raise ValueError(f"Not a JASC-PAL file: {pal_path}")
    
    # lines[1] is version (0100)
    num_colors = int(lines[2])
    
    colors = []
    for i in range(3, 3 + num_colors):
        r, g, b = map(int, lines[i].split())
        colors.append((r, g, b))
    
    return colors


def rgb888_to_rgb555(r: int, g: int, b: int) -> int:
    """Convert 8-bit RGB to GBA RGB555 format"""
    r5 = (r >> 3) & 0x1F
    g5 = (g >> 3) & 0x1F
    b5 = (b >> 3) & 0x1F
    return r5 | (g5 << 5) | (b5 << 10)


def palette_to_gba(colors: list[tuple[int, int, int]]) -> bytes:
    """Convert palette to GBA format (32 bytes for 16 colors)"""
    data = bytearray()
    for r, g, b in colors[:16]:
        rgb555 = rgb888_to_rgb555(r, g, b)
        # Little-endian 16-bit
        data.append(rgb555 & 0xFF)
        data.append((rgb555 >> 8) & 0xFF)
    
    # Pad to 16 colors if needed
    while len(data) < 32:
        data.extend([0, 0])
    
    return bytes(data)


def image_to_tiles(img: Image.Image) -> bytes:
    """
    Convert indexed image to GBA 4bpp tile format.
    
    GBA tiles are 8x8 pixels, 4 bits per pixel.
    Each row of a tile = 4 bytes (8 pixels * 4bpp / 8 = 4 bytes)
    Each tile = 32 bytes
    64x64 image = 8x8 tiles = 64 tiles = 2048 bytes
    
    Pixel packing: Two pixels per byte, low nibble first.
    Byte = (pixel1 & 0x0F) | ((pixel0 & 0x0F) << 4)
    Wait, actually GBA is: Byte = (pixel0 & 0x0F) | ((pixel1 & 0x0F) << 4)
    First pixel in low nibble, second pixel in high nibble.
    """
    if img.mode != 'P':
        raise ValueError(f"Image must be indexed (mode P), got {img.mode}")
    
    width, height = img.size
    if width != 64 or height != 64:
        raise ValueError(f"Image must be 64x64, got {width}x{height}")
    
    pixels = list(img.getdata())
    
    def get_pixel(x: int, y: int) -> int:
        return pixels[y * width + x] & 0x0F
    
    data = bytearray()
    
    # Process 8x8 tiles, row by row of tiles
    for tile_y in range(8):  # 8 rows of tiles
        for tile_x in range(8):  # 8 columns of tiles
            # Process each row within this tile
            for row in range(8):
                img_y = tile_y * 8 + row
                # Process pairs of pixels (4bpp = 2 pixels per byte)
                for col_pair in range(4):
                    img_x = tile_x * 8 + col_pair * 2
                    pixel0 = get_pixel(img_x, img_y)
                    pixel1 = get_pixel(img_x + 1, img_y)
                    # Pack: first pixel in low nibble, second in high
                    byte = (pixel0 & 0x0F) | ((pixel1 & 0x0F) << 4)
                    data.append(byte)
    
    return bytes(data)


def convert_sprite(png_path: Path, pal_path: Path) -> tuple[bytes, bytes]:
    """Convert PNG + palette to GBA format"""
    # Load image
    img = Image.open(png_path)
    
    # Load palette
    colors = parse_jasc_pal(pal_path)
    
    # Convert
    tile_data = image_to_tiles(img)
    pal_data = palette_to_gba(colors)
    
    return tile_data, pal_data


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    png_path = Path(sys.argv[1])
    
    # Auto-detect palette path if not provided
    if len(sys.argv) >= 3:
        pal_path = Path(sys.argv[2])
    else:
        # Try same directory with .pal extension
        pal_path = png_path.parent / (png_path.stem.replace('_front', '').replace('_back', '') + '.pal')
        if not pal_path.exists():
            # Try mega_blaziken.pal style
            parts = png_path.stem.split('_')
            if len(parts) >= 2:
                pal_path = png_path.parent / f"{parts[0]}_{parts[1]}.pal"
    
    if not png_path.exists():
        print(f"PNG not found: {png_path}")
        sys.exit(1)
    
    if not pal_path.exists():
        print(f"Palette not found: {pal_path}")
        print("Provide palette path as second argument")
        sys.exit(1)
    
    print(f"Converting: {png_path}")
    print(f"Palette:    {pal_path}")
    
    tile_data, pal_data = convert_sprite(png_path, pal_path)
    
    # Output paths
    out_tiles = png_path.with_suffix('.tiles.bin')
    out_pal = png_path.with_suffix('.pal.bin')
    
    out_tiles.write_bytes(tile_data)
    out_pal.write_bytes(pal_data)
    
    print(f"Tile data:  {out_tiles} ({len(tile_data)} bytes)")
    print(f"Palette:    {out_pal} ({len(pal_data)} bytes)")
    print("Done!")


if __name__ == '__main__':
    main()
