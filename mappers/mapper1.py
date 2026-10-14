"""
mappers/mapper1.py — MMC1 (Mapper 1)
======================================
Uno de los mappers más populares del NES.
Permite cambiar bancos de PRG y CHR dinámicamente
mediante un registro de desplazamiento serial de 5 bits.

Usado por: The Legend of Zelda, Metroid, Mega Man 2,
           Tetris, Final Fantasy, Castlevania II, etc.
"""


class Mapper1:
    def __init__(self, prg_banks: int, chr_banks: int):
        self.prg_banks = prg_banks
        self.chr_banks = chr_banks

        # Registro de control interno
        self._shift_reg  = 0x10   # bit 4 siempre activo al inicio
        self._control    = 0x0C   # PRG mode 3, CHR mode 0
        self._chr_bank0  = 0
        self._chr_bank1  = 0
        self._prg_bank   = 0

        self.mirror = 0  # 0=single0, 1=single1, 2=vertical, 3=horizontal

    # ─── CPU ───

    def cpu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x6000 <= addr <= 0x7FFF:
            return True, addr & 0x1FFF   # PRG-RAM
        if 0x8000 <= addr <= 0xFFFF:
            prg_mode = (self._control >> 2) & 3
            if prg_mode in (0, 1):
                # 32 KB mode
                bank = (self._prg_bank & 0xFE)
                return True, bank * 0x8000 + (addr & 0x7FFF)
            elif prg_mode == 2:
                # banco bajo fijo en 0, alto variable
                if addr <= 0xBFFF:
                    return True, addr & 0x3FFF
                else:
                    return True, self._prg_bank * 0x4000 + (addr & 0x3FFF)
            else:
                # banco bajo variable, alto fijo al último
                if addr <= 0xBFFF:
                    return True, self._prg_bank * 0x4000 + (addr & 0x3FFF)
                else:
                    return True, (self.prg_banks - 1) * 0x4000 + (addr & 0x3FFF)
        return False, 0

    def cpu_map_write(self, addr: int, data: int) -> tuple[bool, int]:
        if 0x6000 <= addr <= 0x7FFF:
            return True, addr & 0x1FFF   # PRG-RAM write

        if 0x8000 <= addr <= 0xFFFF:
            if data & 0x80:
                # Reset del registro de desplazamiento
                self._shift_reg = 0x10
                self._control  |= 0x0C
            else:
                complete = bool(self._shift_reg & 0x01)
                self._shift_reg = (self._shift_reg >> 1) | ((data & 1) << 4)
                if complete:
                    val = self._shift_reg & 0x1F
                    self._shift_reg = 0x10
                    reg = (addr >> 13) & 3
                    if reg == 0:
                        m = val & 3
                        self.mirror = [2, 2, 1, 0][m]  # simplificado
                        self._control = val
                    elif reg == 1:
                        self._chr_bank0 = val
                    elif reg == 2:
                        self._chr_bank1 = val
                    elif reg == 3:
                        self._prg_bank = val & 0x0F
            return False, 0   # la escritura no va a la ROM
        return False, 0

    # ─── PPU ───

    def ppu_map_read(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF:
            if self.chr_banks == 0:
                return True, addr   # CHR-RAM
            chr_mode = (self._control >> 4) & 1
            if chr_mode == 0:
                # 8 KB mode
                bank = self._chr_bank0 & 0xFE
                return True, bank * 0x2000 + addr
            else:
                # 4 KB mode
                if addr <= 0x0FFF:
                    return True, self._chr_bank0 * 0x1000 + (addr & 0x0FFF)
                else:
                    return True, self._chr_bank1 * 0x1000 + (addr & 0x0FFF)
        return False, 0

    def ppu_map_write(self, addr: int) -> tuple[bool, int]:
        if 0x0000 <= addr <= 0x1FFF and self.chr_banks == 0:
            return True, addr
        return False, 0
