"""
mappers/mapper3.py — CNROM (Mapper 3)
=======================================
PRG fija, CHR switchable.
Usado por: Paperboy, Solomon's Key, Arkanoid, Gradius, etc.
"""


class Mapper3:
    def __init__(self, prg_banks: int, chr_banks: int):
        self.prg_banks  = prg_banks
        self.chr_banks  = chr_banks
        self._chr_bank  = 0

    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x8000 <= addr <= 0xFFFF:
            mask = 0x7FFF if self.prg_banks > 1 else 0x3FFF
            return True, addr & mask
        return False, 0

    def cpu_map_write(self, addr: int, data: int) -> tuple[bool, int]:
        if 0x8000 <= addr <= 0xFFFF:
            self._chr_bank = data & 0x03
        return False, 0

    def ppu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF:
            return True, self._chr_bank * 0x2000 + addr
        return False, 0

    def ppu_map_write(self, addr: int) -> tuple[bool, int]:
        return False, 0
