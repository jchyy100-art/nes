"""
cartridge.py — Lector de ROMs NES (formato iNES / iNES 2.0)
=============================================================
El formato iNES es el estándar para distribuir ROMs del NES.
Estructura del archivo:
    - Header: 16 bytes
    - Trainer (opcional): 512 bytes
    - PRG-ROM: N * 16 KB  (código del juego)
    - CHR-ROM: N * 8 KB   (datos de tiles/sprites)

Header iNES:
    Bytes 0-3  : "NES\x1A" (magic number)
    Byte 4     : Número de bancos PRG-ROM (16 KB cada uno)
    Byte 5     : Número de bancos CHR-ROM (8 KB cada uno)
    Byte 6     : Flags 6 (mapper lo, mirroring, battery, trainer)
    Byte 7     : Flags 7 (mapper hi, NES2.0 id)
    Bytes 8-15 : Resto de flags / padding
"""

import os


# Tipos de espejo de la Name Table (para la PPU)
MIRROR_HORIZONTAL = 0
MIRROR_VERTICAL   = 1
MIRROR_SINGLE_LO  = 2
MIRROR_SINGLE_HI  = 3
MIRROR_FOUR_SCREEN = 4


class Cartridge:
    """
    Representa una ROM del NES cargada en memoria.
    Contiene la PRG-ROM (código) y CHR-ROM (gráficos),
    y proporciona métodos para que el bus la pueda acceder.
    """

    def __init__(self, source: str | bytes | bytearray):
        self.source    = source
        self.path      = source if isinstance(source, str) else "embedded_rom.nes"
        self.prg_rom   = bytearray()   # Código del juego
        self.chr_rom   = bytearray()   # Datos gráficos
        self.chr_ram   = bytearray()   # RAM de caracteres (si no hay CHR-ROM)
        self.prg_ram   = bytearray(8 * 1024)  # SRAM del cartucho (save data)

        self.mapper_id = 0
        self.mirror    = MIRROR_HORIZONTAL
        self.has_battery = False
        self.mapper    = None          # Se asigna después de cargar

        self._load(source)
        self._init_mapper()

    def _load(self, source: str | bytes | bytearray):
        """Lee el archivo .nes o bytes y parsea el header iNES."""
        if isinstance(source, (bytes, bytearray)):
            data = bytes(source)
        else:
            if not os.path.exists(source):
                raise FileNotFoundError(f"ROM no encontrada: {source}")
            with open(source, "rb") as f:
                data = f.read()

        # ─── Verificar magic number ───
        if data[:4] != b"NES\x1a":
            raise ValueError("Archivo inválido: no es una ROM NES (iNES).")

        prg_banks = data[4]   # Número de bancos PRG (16 KB c/u)
        chr_banks = data[5]   # Número de bancos CHR (8 KB c/u)
        flags6    = data[6]
        flags7    = data[7]

        # ─── Mapper ID (bits 4-7 de flags6 = nibble bajo, flags7 = nibble alto) ───
        self.mapper_id = ((flags7 >> 4) << 4) | (flags6 >> 4)

        # ─── Mirroring ───
        if flags6 & 0x08:
            self.mirror = MIRROR_FOUR_SCREEN
        elif flags6 & 0x01:
            self.mirror = MIRROR_VERTICAL
        else:
            self.mirror = MIRROR_HORIZONTAL

        self.has_battery = bool(flags6 & 0x02)

        # ─── Trainer (512 bytes que se ignoran) ───
        offset = 16
        if flags6 & 0x04:
            offset += 512

        # ─── PRG-ROM ───
        prg_size = prg_banks * 16 * 1024
        self.prg_rom = bytearray(data[offset: offset + prg_size])
        offset += prg_size

        # ─── CHR-ROM / CHR-RAM ───
        chr_size = chr_banks * 8 * 1024
        if chr_size > 0:
            self.chr_rom = bytearray(data[offset: offset + chr_size])
        else:
            # Sin CHR-ROM → el juego usa CHR-RAM (8 KB)
            self.chr_ram = bytearray(8 * 1024)

        print(f"[CART] ROM cargada: {os.path.basename(self.path)}")
        print(f"       Mapper: {self.mapper_id}  "
              f"PRG: {prg_banks}×16KB  "
              f"CHR: {chr_banks}×8KB  "
              f"Mirror: {['H','V','SL','SH','4'][self.mirror]}")

    def _init_mapper(self):
        """Instancia el mapper adecuado según el mapper_id."""
        from mappers.mapper0 import Mapper0
        from mappers.mapper1 import Mapper1
        from mappers.mapper2 import Mapper2
        from mappers.mapper3 import Mapper3
        from mappers.mapper4 import Mapper4

        mappers = {
            0: Mapper0,
            1: Mapper1,
            2: Mapper2,
            3: Mapper3,
            4: Mapper4,
        }

        cls = mappers.get(self.mapper_id)
        if cls is None:
            raise NotImplementedError(
                f"Mapper {self.mapper_id} no está implementado todavía.")

        prg_banks = len(self.prg_rom) // (16 * 1024)
        chr_banks = len(self.chr_rom) // (8 * 1024) if self.chr_rom else 0
        self.mapper = cls(prg_banks, chr_banks)
        if not hasattr(self.mapper, 'mirror'):
            self.mapper.mirror = self.mirror


    # ─── Acceso desde la CPU (PRG) ───

    def cpu_read(self, addr: int) -> tuple[bool, int]:
        """
        Intenta leer desde el cartucho en la dirección dada.
        Devuelve (True, dato) si el cartucho maneja esa dirección,
        o (False, 0) si no.
        """
        mapped, mapped_addr = self.mapper.cpu_map_read(addr)
        if not mapped:
            return False, 0

        # PRG-RAM ($6000-$7FFF)
        if addr >= 0x6000 and addr <= 0x7FFF:
            return True, self.prg_ram[addr - 0x6000]

        return True, self.prg_rom[mapped_addr % len(self.prg_rom)]

    def cpu_write(self, addr: int, data: int) -> bool:
        """
        Intenta escribir en el cartucho.
        Algunos mappers capturan escrituras para cambiar bancos.
        """
        mapped, mapped_addr = self.mapper.cpu_map_write(addr, data)
        if not mapped:
            return False

        if addr >= 0x6000 and addr <= 0x7FFF:
            self.prg_ram[addr - 0x6000] = data
        return True

    # ─── Acceso desde la PPU (CHR) ───

    def ppu_read(self, addr: int) -> tuple[bool, int]:
        """Lee datos de patrones (tiles) para la PPU."""
        mapped, mapped_addr = self.mapper.ppu_map_read(addr)
        if not mapped:
            return False, 0

        if self.chr_rom:
            return True, self.chr_rom[mapped_addr % len(self.chr_rom)]
        else:
            return True, self.chr_ram[mapped_addr % len(self.chr_ram)]

    def ppu_write(self, addr: int, data: int) -> bool:
        """Escribe en CHR-RAM (si el cartucho la tiene)."""
        mapped, mapped_addr = self.mapper.ppu_map_write(addr)
        if not mapped:
            return False
        if not self.chr_rom:
            self.chr_ram[mapped_addr % len(self.chr_ram)] = data
            return True
        return False

    @property
    def mirror_mode(self) -> int:
        """Algunos mappers pueden cambiar el mirror dinámicamente."""
        return self.mapper.mirror

