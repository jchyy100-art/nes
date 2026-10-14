"""
mappers/mapper4.py — MMC3 (Mapper 4)
======================================
Mapper muy popular con soporte para IRQ de scanline.
Usado por: Super Mario Bros. 3, Mega Man 3-6,
           Teenage Mutant Ninja Turtles, Kirby's Adventure, etc.
"""


class Mapper4:
    def __init__(self, prg_banks: int, chr_banks: int):
        self.prg_banks   = prg_banks
        self.chr_banks   = chr_banks
        self.mirror      = 0

        # Registros de banco
        self._bank_reg   = [0] * 8
        self._bank_select = 0

        # IRQ
        self._irq_enable  = False
        self._irq_counter = 0
        self._irq_latch   = 0
        self._irq_pending = False

    # ─── Acceso a bancos ───

    def _prg(self, n: int) -> int:
        return (n % self.prg_banks) * 0x2000

    def _chr(self, n: int) -> int:
        total = max(self.chr_banks * 8, 1)
        return (n % total) * 0x0400

    # ─── CPU ───

    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x6000 <= addr <= 0x7FFF:
            return True, addr & 0x1FFF
        if 0x8000 <= addr <= 0x9FFF:
            if self._bank_select & 0x40:
                return True, self._prg((self.prg_banks * 2 - 2)) + (addr & 0x1FFF)
            return True, self._prg(self._bank_reg[6]) + (addr & 0x1FFF)
        if 0xA000 <= addr <= 0xBFFF:
            return True, self._prg(self._bank_reg[7]) + (addr & 0x1FFF)
        if 0xC000 <= addr <= 0xDFFF:
            if self._bank_select & 0x40:
                return True, self._prg(self._bank_reg[6]) + (addr & 0x1FFF)
            return True, self._prg((self.prg_banks * 2 - 2)) + (addr & 0x1FFF)
        if 0xE000 <= addr <= 0xFFFF:
            return True, self._prg((self.prg_banks * 2 - 1)) + (addr & 0x1FFF)
        return False, 0

    def cpu_map_write(self, addr: int, data: int) -> tuple[bool, int]:
        if 0x6000 <= addr <= 0x7FFF:
            return True, addr & 0x1FFF
        if 0x8000 <= addr <= 0x9FFF:
            if addr & 1:
                self._bank_reg[self._bank_select & 7] = data
            else:
                self._bank_select = data
        elif 0xA000 <= addr <= 0xBFFF:
            if not (addr & 1):
                self.mirror = 1 if (data & 1) else 0
        elif 0xC000 <= addr <= 0xDFFF:
            if addr & 1:
                self._irq_counter = 0
            else:
                self._irq_latch = data
        elif 0xE000 <= addr <= 0xFFFF:
            if addr & 1:
                self._irq_enable  = True
            else:
                self._irq_enable  = False
                self._irq_pending = False
        return False, 0

    # ─── PPU ───

    def ppu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF:
            if self.chr_banks == 0:
                return True, addr
            invert = bool(self._bank_select & 0x80)
            fine   = addr & 0x07FF
            table  = (addr >> 10) & 7  # 0-7 para cada 1KB
            if not invert:
                if table < 2:
                    bank = self._bank_reg[table] & 0xFE
                    return True, self._chr(bank) + fine + ((addr & 0x0400) >> 10) * 0x400
                else:
                    bank = self._bank_reg[2 + (table - 2)]
                    return True, self._chr(bank) + fine
            else:
                if table >= 4:
                    bank = self._bank_reg[(table - 4)] & 0xFE
                    return True, self._chr(bank) + fine + ((addr & 0x0400) >> 10) * 0x400
                else:
                    bank = self._bank_reg[2 + table]
                    return True, self._chr(bank) + fine
        return False, 0

    def ppu_map_write(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF and self.chr_banks == 0:
            return True, addr
        return False, 0

    def scanline(self):
        """Llamado por la PPU al final de cada scanline (para IRQ)."""
        if self._irq_counter == 0:
            self._irq_counter = self._irq_latch
        else:
            self._irq_counter -= 1
        if self._irq_counter == 0 and self._irq_enable:
            self._irq_pending = True

    def irq_pending(self) -> bool:
        pending = self._irq_pending
        self._irq_pending = False
        return pending
