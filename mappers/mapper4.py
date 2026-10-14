"""
mappers/mapper4.py — MMC3 (Mapper 4)
======================================
Mapper con soporte para cambio de bancos PRG/CHR y contador de scanline IRQ.
Usado por: Super Mario Bros. 3, Mega Man 3-6, Kirby's Adventure, etc.
"""

from cartridge import MIRROR_HORIZONTAL, MIRROR_VERTICAL


class Mapper4:
    def __init__(self, prg_banks: int, chr_banks: int):
        self.prg_banks   = prg_banks   # Cantidad de bancos de 16 KB
        self.chr_banks   = chr_banks   # Cantidad de bancos de 8 KB
        self.mirror      = MIRROR_VERTICAL

        # Registros de banco (R0-R7)
        self._bank_reg   = [0] * 8
        self._bank_select = 0

        # IRQ
        self._irq_enable  = False
        self._irq_counter = 0
        self._irq_latch   = 0
        self._irq_reload  = False
        self._irq_pending = False

    # ─── Cálculos de offset ───

    def _prg(self, n: int) -> int:
        total_8k = max(self.prg_banks * 2, 1)
        return (n % total_8k) * 0x2000

    def _chr(self, n: int) -> int:
        total_1k = max(self.chr_banks * 8, 1)
        return (n % total_1k) * 0x0400

    # ─── Mapeo de CPU ───

    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        total_8k = max(self.prg_banks * 2, 1)

        # PRG-RAM ($6000-$7FFF)
        if 0x6000 <= addr <= 0x7FFF:
            return True, addr & 0x1FFF

        # PRG-ROM ($8000-$FFFF) dividida en 4 bancos de 8 KB
        if 0x8000 <= addr <= 0x9FFF:
            if self._bank_select & 0x40:
                bank = total_8k - 2   # Fijo a penúltimo banco
            else:
                bank = self._bank_reg[6]
            return True, self._prg(bank) + (addr & 0x1FFF)

        elif 0xA000 <= addr <= 0xBFFF:
            bank = self._bank_reg[7]
            return True, self._prg(bank) + (addr & 0x1FFF)

        elif 0xC000 <= addr <= 0xDFFF:
            if self._bank_select & 0x40:
                bank = self._bank_reg[6]
            else:
                bank = total_8k - 2   # Fijo a penúltimo banco
            return True, self._prg(bank) + (addr & 0x1FFF)

        elif 0xE000 <= addr <= 0xFFFF:
            bank = total_8k - 1       # Fijo al último banco
            return True, self._prg(bank) + (addr & 0x1FFF)

        return False, 0

    def cpu_map_write(self, addr: int, data: int) -> tuple[bool, int]:
        if 0x6000 <= addr <= 0x7FFF:
            return True, addr & 0x1FFF

        if 0x8000 <= addr <= 0x9FFF:
            if addr & 1:
                # $8001: Bank data
                self._bank_reg[self._bank_select & 7] = data
            else:
                # $8000: Bank select
                self._bank_select = data
            return True, 0

        elif 0xA000 <= addr <= 0xBFFF:
            if not (addr & 1):
                # $A000: Mirroring (0 = Vertical, 1 = Horizontal)
                self.mirror = MIRROR_HORIZONTAL if (data & 1) else MIRROR_VERTICAL
            return True, 0

        elif 0xC000 <= addr <= 0xDFFF:
            if addr & 1:
                # $C001: IRQ Reload
                self._irq_reload = True
            else:
                # $C000: IRQ Latch
                self._irq_latch = data
            return True, 0

        elif 0xE000 <= addr <= 0xFFFF:
            if addr & 1:
                # $E001: IRQ Enable
                self._irq_enable = True
            else:
                # $E000: IRQ Disable
                self._irq_enable = False
                self._irq_pending = False
            return True, 0

        return False, 0

    # ─── Mapeo de PPU ───

    def ppu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF:
            if self.chr_banks == 0:
                return True, addr

            invert = bool(self._bank_select & 0x80)
            slot = (addr >> 10) & 7   # 8 slots de 1 KB cada uno
            offset = addr & 0x03FF

            if not invert:
                # R0: 2 KB en $0000-$07FF (slots 0, 1)
                if slot == 0:
                    bank = self._bank_reg[0] & 0xFE
                elif slot == 1:
                    bank = (self._bank_reg[0] & 0xFE) + 1
                # R1: 2 KB en $0800-$0FFF (slots 2, 3)
                elif slot == 2:
                    bank = self._bank_reg[1] & 0xFE
                elif slot == 3:
                    bank = (self._bank_reg[1] & 0xFE) + 1
                # R2-R5: 1 KB c/u en $1000-$1FFF (slots 4, 5, 6, 7)
                elif slot == 4:
                    bank = self._bank_reg[2]
                elif slot == 5:
                    bank = self._bank_reg[3]
                elif slot == 6:
                    bank = self._bank_reg[4]
                else:
                    bank = self._bank_reg[5]
            else:
                # Invertido: R2-R5 en $0000-$0FFF
                if slot == 0:
                    bank = self._bank_reg[2]
                elif slot == 1:
                    bank = self._bank_reg[3]
                elif slot == 2:
                    bank = self._bank_reg[4]
                elif slot == 3:
                    bank = self._bank_reg[5]
                # R0 en $1000-$17FF (slots 4, 5)
                elif slot == 4:
                    bank = self._bank_reg[0] & 0xFE
                elif slot == 5:
                    bank = (self._bank_reg[0] & 0xFE) + 1
                # R1 en $1800-$1FFF (slots 6, 7)
                elif slot == 6:
                    bank = self._bank_reg[1] & 0xFE
                else:
                    bank = (self._bank_reg[1] & 0xFE) + 1

            return True, self._chr(bank) + offset

        return False, 0

    def ppu_map_write(self, addr: int, *args) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF and self.chr_banks == 0:
            return True, addr
        return False, 0

    def scanline(self):
        """Llamado en cada scanline visible por la PPU para el contador IRQ."""
        if self._irq_counter == 0 or self._irq_reload:
            self._irq_counter = self._irq_latch
            self._irq_reload = False
        else:
            self._irq_counter -= 1

        if self._irq_counter == 0 and self._irq_enable:
            self._irq_pending = True

    def irq_pending(self) -> bool:
        pending = self._irq_pending
        self._irq_pending = False
        return pending
