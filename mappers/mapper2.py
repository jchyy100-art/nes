"""
mappers/mapper2.py — UxROM (Mapper 2)
=======================================
PRG-ROM switchable en el banco bajo, banco alto siempre fijo al último.
Usado por: Mega Man, Contra, Castlevania, Duck Tales, etc.
"""


class Mapper2:
    def __init__(self, prg_banks: int, chr_banks: int):
        self.prg_banks   = prg_banks
        self.chr_banks   = chr_banks
        self._prg_bank_lo = 0
        self._prg_bank_hi = prg_banks - 1

    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x8000 <= addr <= 0xBFFF:
            return True, self._prg_bank_lo * 0x4000 + (addr & 0x3FFF)
        if 0xC000 <= addr <= 0xFFFF:
            return True, self._prg_bank_hi * 0x4000 + (addr & 0x3FFF)
        return False, 0

    def cpu_map_write(self, addr: int, data: int) -> tuple[bool, int]:
        if 0x8000 <= addr <= 0xFFFF:
            self._prg_bank_lo = data & 0x0F
        return False, 0

    def ppu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF:
            return True, addr
        return False, 0

    def ppu_map_write(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF and self.chr_banks == 0:
            return True, addr
        return False, 0
