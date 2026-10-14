"""
mappers/mapper0.py — NROM (Mapper 0)
=====================================
El mapper más simple del NES. No cambia bancos.
Usado por juegos clásicos como Donkey Kong, Mario Bros.,
Balloon Fight, Ice Climber, etc.

PRG-ROM:
    16 KB → mapeado en $8000-$BFFF Y $C000-$FFFF (espejo)
    32 KB → mapeado en $8000-$FFFF

CHR-ROM:
    8 KB → $0000-$1FFF (sin cambios)
"""


class Mapper0:
    def __init__(self, prg_banks: int, chr_banks: int):
        self.prg_banks = prg_banks   # 1 o 2
        self.chr_banks = chr_banks   # generalmente 1

    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x8000 <= addr <= 0xFFFF:
            # Si solo hay 1 banco de 16 KB, hacemos espejo en $C000
            mask = 0x7FFF if self.prg_banks > 1 else 0x3FFF
            return True, addr & mask
        return False, 0

    def cpu_map_write(self, addr: int, data: int) -> tuple[bool, int]:
        # NROM no tiene escritura mapeada
        return False, 0

    def ppu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF:
            return True, addr
        return False, 0

    def ppu_map_write(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF:
            if self.chr_banks == 0:   # CHR-RAM
                return True, addr
        return False, 0
