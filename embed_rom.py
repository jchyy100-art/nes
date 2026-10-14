"""
embed_rom.py — Utilidad para incrustar ROMs directamente en el código Python
=============================================================================
Este script convierte cualquier archivo .nes a una cadena Base64
y genera 'embedded_rom.py'. De esta manera, el juego viaja integrado
dentro del código del servidor y no requiere subir archivos manualmente.

Uso:
    python embed_rom.py mi_juego.nes
    python embed_rom.py --test-rom
"""

import sys
import os
import base64


def create_minimal_test_rom() -> bytes:
    """
    Genera una ROM de prueba minimalista legal (formato iNES Mapper 0).
    Muestra una pantalla con colores y prueba el ciclo del PPU.
    """
    header = bytearray(16)
    header[0:4] = b"NES\x1a"
    header[4] = 1   # 1 banco PRG (16 KB)
    header[5] = 1   # 1 banco CHR (8 KB)

    # 16 KB PRG
    prg = bytearray(16 * 1024)

    # Código 6502 en $8000:
    # SEI ($78), CLD ($D8), LDX #$FF ($A2 $FF), TXS ($9A)
    # Escribe paleta en PPU $3F00
    code = [
        # ── Init CPU ──
        0x78,             # $8000: SEI
        0xD8,             # $8001: CLD
        0xA2, 0xFF,       # $8002: LDX #$FF
        0x9A,             # $8004: TXS
        # ── Wait VBlank ──
        0x2C, 0x02, 0x20, # $8005: BIT $2002  (also resets w toggle)
        0x10, 0xFB,       # $8008: BPL $8005
        # ── Write palette at $3F00 ──
        # BIT $2002 already reset the w toggle to 0
        0xA9, 0x3F,       # $800A: LDA #$3F
        0x8D, 0x06, 0x20, # $800C: STA $2006  (high byte = $3F, w -> 1)
        0xA9, 0x00,       # $800F: LDA #$00
        0x8D, 0x06, 0x20, # $8011: STA $2006  (low byte = $00, w -> 0) => addr=$3F00
        # ── Write 32 palette colors ──
        0xA2, 0x00,       # $8014: LDX #$00
        # loop_palette:
        0x8A,             # $8016: TXA
        0x8D, 0x07, 0x20, # $8017: STA $2007  (PPUDATA)
        0xE8,             # $801A: INX
        0xE0, 0x20,       # $801B: CPX #$20
        0xD0, 0xF8,       # $801D: BNE $8016 (loop_palette)
        # ── Fill nametable 0 ($2000) with tile pattern ──
        0xA9, 0x20,       # $801F: LDA #$20
        0x8D, 0x06, 0x20, # $8021: STA $2006
        0xA9, 0x00,       # $8024: LDA #$00
        0x8D, 0x06, 0x20, # $8026: STA $2006  => addr=$2000
        0xA2, 0x00,       # $8029: LDX #$00
        0xA0, 0x04,       # $802B: LDY #$04   (4 pages = 1024 bytes)
        # loop_nt:
        0x8A,             # $802D: TXA
        0x8D, 0x07, 0x20, # $802E: STA $2007
        0xE8,             # $8031: INX
        0xD0, 0xFA,       # $8032: BNE $802D
        0x88,             # $8034: DEY
        0xD0, 0xF7,       # $8035: BNE $802D
        # ── Enable NMI + use BG pattern table 1 ──
        0xA9, 0x90,       # $8037: LDA #$90   (NMI on, BG table = $1000)
        0x8D, 0x00, 0x20, # $8039: STA $2000  (PPUCTRL)
        # ── Enable rendering ──
        0xA9, 0x1E,       # $803C: LDA #$1E
        0x8D, 0x01, 0x20, # $803E: STA $2001  (PPUMASK)
        # ── Reset scroll ──
        0xA9, 0x00,       # $8041: LDA #$00
        0x8D, 0x05, 0x20, # $8043: STA $2005  (PPUSCROLL X=0)
        0x8D, 0x05, 0x20, # $8046: STA $2005  (PPUSCROLL Y=0)
        # ── Infinite loop ──
        0x4C, 0x49, 0x80, # $8049: JMP $8049
    ]

    for i, b in enumerate(code):
        prg[i] = b

    # Vectores de interrupción al final de los 16 KB ($3FFA - $3FFF)
    # NMI: $8000
    prg[0x3FFA] = 0x00; prg[0x3FFB] = 0x80
    # RESET: $8000
    prg[0x3FFC] = 0x00; prg[0x3FFD] = 0x80
    # IRQ: $8000
    prg[0x3FFE] = 0x00; prg[0x3FFF] = 0x80

    # 8 KB CHR (patrones de píxeles básicos)
    chr_rom = bytearray(8 * 1024)
    # Crear un patrón de tablero de ajedrez / barras para el primer tile
    for i in range(16):
        chr_rom[i] = 0xFF if (i % 2 == 0) else 0x55

    return bytes(header + prg + chr_rom)


def embed_rom(rom_path: str = None, test_mode: bool = False):
    target_file = os.path.join(os.path.dirname(__file__), "embedded_rom.py")

    if test_mode or not rom_path:
        print("[EMBED] Generando ROM de prueba por defecto...")
        rom_bytes = create_minimal_test_rom()
        rom_name = "NES_DEMO_TEST_ROM.nes"
    else:
        if not os.path.exists(rom_path):
            print(f"[ERROR] Archivo no encontrado: {rom_path}")
            sys.exit(1)
        with open(rom_path, "rb") as f:
            rom_bytes = f.read()
        rom_name = os.path.basename(rom_path)

    b64_data = base64.b64encode(rom_bytes).decode("ascii")

    content = f'''"""
embedded_rom.py — ROM incrustada en el código
================================================
Generado automáticamente por embed_rom.py.
Nombre original: {rom_name}
Tamaño: {len(rom_bytes)} bytes
"""

import base64

ROM_NAME = {repr(rom_name)}
ROM_BASE64 = """{b64_data}"""


def get_rom_bytes() -> bytes:
    """Devuelve los bytes binarios de la ROM incrustada."""
    return base64.b64decode(ROM_BASE64)
'''

    with open(target_file, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[OK] ROM incrustada con exito!")
    print(f"   Juego: {rom_name}")
    print(f"   Tamano: {len(rom_bytes) / 1024:.1f} KB")
    print(f"   Archivo generado: {target_file}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--test-rom":
        embed_rom(sys.argv[1])
    else:
        embed_rom(test_mode=True)
