"""
ppu.py — Picture Processing Unit (PPU) del NES
================================================
La PPU genera la imagen del NES a 256×240 píxeles,
60 fotogramas por segundo.

Memoria interna de la PPU:
    $0000-$0FFF : Pattern Table 0 (tiles del background)
    $1000-$1FFF : Pattern Table 1 (tiles de sprites)
    $2000-$23FF : Name Table 0 (mapa de pantalla)
    $2400-$27FF : Name Table 1
    $2800-$2BFF : Name Table 2
    $2C00-$2FFF : Name Table 3
    $3000-$3EFF : Espejo de $2000-$2EFF
    $3F00-$3F0F : Paleta de fondo (16 colores)
    $3F10-$3F1F : Paleta de sprites (16 colores)
    $3F20-$3FFF : Espejos de paletas

Registros mapeados en CPU ($2000-$2007):
    $2000 PPUCTRL   — control general
    $2001 PPUMASK   — control de renderizado
    $2002 PPUSTATUS — estado (lectura)
    $2003 OAMADDR   — dirección de OAM
    $2004 OAMDATA   — datos de OAM
    $2005 PPUSCROLL — scroll
    $2006 PPUADDR   — dirección VRAM
    $2007 PPUDATA   — datos VRAM

OAM (Object Attribute Memory): 64 sprites × 4 bytes
    Byte 0: Posición Y
    Byte 1: Índice de tile
    Byte 2: Atributos (paleta, flip, prioridad)
    Byte 3: Posición X
"""

import numpy as np
from cartridge import MIRROR_HORIZONTAL, MIRROR_VERTICAL, MIRROR_SINGLE_LO, MIRROR_SINGLE_HI


# ── Paleta de colores del NES (RGB) ─────────────────────────────────────────
# 64 colores oficiales del NES (formato RGB de 8 bits por canal)
NES_PALETTE = [
    (84,84,84),(0,30,116),(8,16,144),(48,0,136),(68,0,100),(92,0,48),(84,4,0),
    (60,24,0),(32,42,0),(8,58,0),(0,64,0),(0,60,0),(0,50,60),(0,0,0),(0,0,0),(0,0,0),
    (152,150,152),(8,76,196),(48,50,236),(92,30,228),(136,20,176),(160,20,100),
    (152,34,32),(120,60,0),(84,90,0),(40,114,0),(8,124,0),(0,118,40),(0,102,120),
    (0,0,0),(0,0,0),(0,0,0),
    (236,238,236),(76,154,236),(120,124,236),(176,98,236),(228,84,236),(236,88,180),
    (236,106,100),(212,136,32),(160,170,0),(116,196,0),(76,208,32),(56,204,108),
    (56,180,204),(60,60,60),(0,0,0),(0,0,0),
    (236,238,236),(168,204,236),(188,188,236),(212,178,236),(236,174,236),
    (236,174,212),(236,180,176),(228,196,144),(204,210,120),(180,222,120),
    (168,226,144),(152,226,180),(160,214,228),(160,162,160),(0,0,0),(0,0,0),
]


class PPU:
    """
    Emula la PPU del NES (Ricoh 2C02).
    """

    # ─── Dimensiones del NES ───
    SCREEN_W = 256
    SCREEN_H = 240

    def __init__(self, bus):
        self.bus = bus

        # ─── Memoria interna de la PPU ───
        # Name tables: 2 físicas de 1 KB (con espejo según cartucho)
        self.name_table  = [bytearray(1024), bytearray(1024)]
        # Paleta de colores (32 bytes)
        self.palette     = bytearray(32)
        # OAM: 64 sprites × 4 bytes
        self.oam         = bytearray(256)
        # OAM secundaria (sprites de la scanline actual, máx 8)
        self._oam2       = [bytearray(4) for _ in range(8)]

        # ─── Registros internos de la PPU ───
        self._ctrl   = 0x00   # $2000 PPUCTRL
        self._mask   = 0x00   # $2001 PPUMASK
        self._status = 0x00   # $2002 PPUSTATUS
        self._oam_addr = 0    # $2003 OAMADDR

        # Registros de scroll/dirección (Loopy)
        self._v = 0x0000   # VRAM address actual
        self._t = 0x0000   # VRAM address temporal (latch)
        self._x = 0        # fine X scroll (3 bits)
        self._w = 0        # write toggle (0 o 1)

        # Latch de datos
        self._data_buffer = 0x00

        # ─── Posición del rayo (scanline, ciclo) ───
        self.scanline  = 0
        self.cycle     = 0
        self.frame     = 0

        # ─── Flags de sincronización con la CPU ───
        self.nmi_occurred  = False   # True cuando la PPU genera NMI
        self.frame_ready   = False   # True cuando un frame está completo
        self._odd_frame    = False

        # ─── Framebuffer (numpy array para pygame) ───
        # shape: (240, 256, 3) — RGB
        self.framebuffer = np.zeros((self.SCREEN_H, self.SCREEN_W, 3),
                                    dtype=np.uint8)
        # Buffer de trabajo (el que se está dibujando)
        self._back_buffer = np.zeros((self.SCREEN_H, self.SCREEN_W, 3),
                                     dtype=np.uint8)

        # ─── Registros de renderizado interno ───
        self._bg_next_tile_id   = 0x00
        self._bg_next_tile_attr = 0x00
        self._bg_next_tile_lsb  = 0x00
        self._bg_next_tile_msb  = 0x00

        # Shift registers del background (16 bits cada uno)
        self._bg_shifter_pattern_lo = 0x0000
        self._bg_shifter_pattern_hi = 0x0000
        self._bg_shifter_attr_lo    = 0x0000
        self._bg_shifter_attr_hi    = 0x0000

        # Datos de sprites de la scanline actual
        self._sprite_count = 0
        self._sprite_shifter_lo = [0] * 8
        self._sprite_shifter_hi = [0] * 8
        self._sprite_attr        = [0] * 8
        self._sprite_x_counter   = [0] * 8
        self._sprite_zero_hit_possible  = False
        self._sprite_zero_being_rendered = False

    # ═══════════════════════════════════════════════════════════════════════
    #                    LECTURA DE REGISTROS (CPU → PPU)
    # ═══════════════════════════════════════════════════════════════════════

    def cpu_read(self, addr: int) -> int:
        addr &= 0x07   # Solo 3 bits (8 registros)
        data = 0x00

        if addr == 0x02:   # PPUSTATUS
            # Los 3 bits altos son el estado real; los 5 bajos son basura del buffer
            data = (self._status & 0xE0) | (self._data_buffer & 0x1F)
            self._status &= ~0x80   # limpiar VBlank flag
            self._w = 0             # reset write toggle

        elif addr == 0x04:   # OAMDATA
            data = self.oam[self._oam_addr]

        elif addr == 0x07:   # PPUDATA
            data = self._data_buffer
            self._data_buffer = self.ppu_read(self._v)
            if self._v >= 0x3F00:   # paleta: no hay delay
                data = self._data_buffer
            # Auto-increment
            inc = 32 if (self._ctrl & 0x04) else 1
            self._v = (self._v + inc) & 0x7FFF

        return data

    # ═══════════════════════════════════════════════════════════════════════
    #                   ESCRITURA DE REGISTROS (CPU → PPU)
    # ═══════════════════════════════════════════════════════════════════════

    def cpu_write(self, addr: int, data: int):
        addr &= 0x07

        if addr == 0x00:   # PPUCTRL
            self._ctrl = data
            # t: ...BA.. ........ = d: ......BA
            self._t = (self._t & 0xF3FF) | ((data & 0x03) << 10)

        elif addr == 0x01:   # PPUMASK
            self._mask = data

        elif addr == 0x03:   # OAMADDR
            self._oam_addr = data

        elif addr == 0x04:   # OAMDATA
            self.oam[self._oam_addr] = data
            self._oam_addr = (self._oam_addr + 1) & 0xFF

        elif addr == 0x05:   # PPUSCROLL
            if self._w == 0:
                self._x = data & 0x07
                self._t = (self._t & 0xFFE0) | (data >> 3)
                self._w = 1
            else:
                self._t = (self._t & 0x8FFF) | ((data & 0x07) << 12)
                self._t = (self._t & 0xFC1F) | ((data & 0xF8) << 2)
                self._w = 0

        elif addr == 0x06:   # PPUADDR
            if self._w == 0:
                self._t = (self._t & 0x00FF) | ((data & 0x3F) << 8)
                self._w = 1
            else:
                self._t = (self._t & 0xFF00) | data
                self._v = self._t
                self._w = 0

        elif addr == 0x07:   # PPUDATA
            self.ppu_write(self._v, data)
            inc = 32 if (self._ctrl & 0x04) else 1
            self._v = (self._v + inc) & 0x7FFF

    # ═══════════════════════════════════════════════════════════════════════
    #                      LECTURA / ESCRITURA INTERNA
    # ═══════════════════════════════════════════════════════════════════════

    def ppu_read(self, addr: int) -> int:
        addr &= 0x3FFF
        ok, data = self.bus.cart.ppu_read(addr)
        if ok:
            return data

        if addr <= 0x1FFF:
            return 0   # sin CHR

        elif addr <= 0x3EFF:
            addr &= 0x0FFF
            return self.name_table[self._mirror_addr(addr)][addr & 0x03FF]

        elif addr <= 0x3FFF:
            addr &= 0x1F
            # Espejos de transparencia
            if addr in (0x10, 0x14, 0x18, 0x1C):
                addr -= 0x10
            return self.palette[addr]

        return 0

    def ppu_write(self, addr: int, data: int):
        addr &= 0x3FFF
        if self.bus.cart.ppu_write(addr, data):
            return

        if addr <= 0x1FFF:
            pass   # sin CHR-RAM aquí (maneja el cartucho)

        elif addr <= 0x3EFF:
            addr &= 0x0FFF
            self.name_table[self._mirror_addr(addr)][addr & 0x03FF] = data

        elif addr <= 0x3FFF:
            addr &= 0x1F
            if addr in (0x10, 0x14, 0x18, 0x1C):
                addr -= 0x10
            self.palette[addr] = data

    def _mirror_addr(self, addr: int) -> int:
        """Devuelve 0 o 1 según el modo de espejo del cartucho."""
        mode = self.bus.cart.mirror_mode
        if mode == MIRROR_VERTICAL:
            return (addr >> 10) & 1
        elif mode == MIRROR_HORIZONTAL:
            return (addr >> 11) & 1
        elif mode == MIRROR_SINGLE_LO:
            return 0
        elif mode == MIRROR_SINGLE_HI:
            return 1
        return 0

    # ═══════════════════════════════════════════════════════════════════════
    #                        RENDERIZADO
    # ═══════════════════════════════════════════════════════════════════════

    def _get_color(self, palette_idx: int, pixel: int) -> tuple:
        """Devuelve el color RGB de la paleta del NES."""
        addr = 0x3F00 + (palette_idx << 2) + pixel
        idx  = self.ppu_read(addr) & 0x3F
        return NES_PALETTE[idx]

    def _load_bg_shifters(self):
        self._bg_shifter_pattern_lo = (
            (self._bg_shifter_pattern_lo & 0xFF00) | self._bg_next_tile_lsb)
        self._bg_shifter_pattern_hi = (
            (self._bg_shifter_pattern_hi & 0xFF00) | self._bg_next_tile_msb)
        self._bg_shifter_attr_lo = (
            (self._bg_shifter_attr_lo & 0xFF00) |
            (0xFF if (self._bg_next_tile_attr & 0x01) else 0x00))
        self._bg_shifter_attr_hi = (
            (self._bg_shifter_attr_hi & 0xFF00) |
            (0xFF if (self._bg_next_tile_attr & 0x02) else 0x00))

    def _update_shifters(self):
        if self._mask & 0x08:   # BG enable
            self._bg_shifter_pattern_lo = (self._bg_shifter_pattern_lo << 1) & 0xFFFF
            self._bg_shifter_pattern_hi = (self._bg_shifter_pattern_hi << 1) & 0xFFFF
            self._bg_shifter_attr_lo    = (self._bg_shifter_attr_lo    << 1) & 0xFFFF
            self._bg_shifter_attr_hi    = (self._bg_shifter_attr_hi    << 1) & 0xFFFF

        if (self._mask & 0x10) and self.cycle >= 1 and self.cycle < 258:
            for i in range(self._sprite_count):
                if self._sprite_x_counter[i] > 0:
                    self._sprite_x_counter[i] -= 1
                else:
                    self._sprite_shifter_lo[i] = (self._sprite_shifter_lo[i] << 1) & 0xFF
                    self._sprite_shifter_hi[i] = (self._sprite_shifter_hi[i] << 1) & 0xFF

    # ─── Scroll helpers (Loopy) ───

    def _inc_scroll_x(self):
        if self._mask & 0x18:   # rendering enable
            if (self._v & 0x001F) == 31:
                self._v &= ~0x001F
                self._v ^= 0x0400
            else:
                self._v += 1

    def _inc_scroll_y(self):
        if self._mask & 0x18:
            if (self._v & 0x7000) != 0x7000:
                self._v += 0x1000
            else:
                self._v &= ~0x7000
                y = (self._v & 0x03E0) >> 5
                if y == 29:
                    y = 0
                    self._v ^= 0x0800
                elif y == 31:
                    y = 0
                else:
                    y += 1
                self._v = (self._v & ~0x03E0) | (y << 5)

    def _transfer_addr_x(self):
        if self._mask & 0x18:
            self._v = (self._v & ~0x041F) | (self._t & 0x041F)

    def _transfer_addr_y(self):
        if self._mask & 0x18:
            self._v = (self._v & ~0x7BE0) | (self._t & 0x7BE0)

    # ═══════════════════════════════════════════════════════════════════════
    #                        CICLO PRINCIPAL
    # ═══════════════════════════════════════════════════════════════════════

    def clock(self):
        """
        Avanza la PPU un ciclo de reloj.
        La PPU corre 3 ciclos por cada ciclo de CPU.
        """
        sl = self.scanline
        cy = self.cycle

        # ─── Scanlines visibles + scanline pre-render (-1 / 261) ───
        if sl >= -1 and sl < 240:

            # ── Scanline pre-render: limpiar flags ──
            if sl == -1 and cy == 1:
                self._status &= ~0xE0   # limpiar VBlank, sprite0, overflow
                for i in range(8):
                    self._sprite_shifter_lo[i] = 0
                    self._sprite_shifter_hi[i] = 0

            # ── Ciclos de renderizado de BG (2-257 y 321-338) ──
            if (2 <= cy <= 257) or (321 <= cy <= 337):
                self._update_shifters()

                phase = (cy - 1) & 7   # fase dentro del tile (0-7)

                if phase == 0:
                    self._load_bg_shifters()
                    # Leer el ID del tile de la name table
                    nt_addr = 0x2000 | (self._v & 0x0FFF)
                    self._bg_next_tile_id = self.ppu_read(nt_addr)

                elif phase == 2:
                    # Leer el atributo del tile
                    at_addr = (0x23C0 |
                                (self._v & 0x0C00) |
                                ((self._v >> 4) & 0x38) |
                                ((self._v >> 2) & 0x07))
                    attr = self.ppu_read(at_addr)
                    if self._v & 0x0040: attr >>= 4
                    if self._v & 0x0002: attr >>= 2
                    self._bg_next_tile_attr = attr & 0x03

                elif phase == 4:
                    # Leer el byte bajo del tile (patrón)
                    bg_table = 0x1000 if (self._ctrl & 0x10) else 0x0000
                    fine_y = (self._v >> 12) & 7
                    self._bg_next_tile_lsb = self.ppu_read(
                        bg_table + self._bg_next_tile_id * 16 + fine_y)

                elif phase == 6:
                    # Leer el byte alto del tile
                    bg_table = 0x1000 if (self._ctrl & 0x10) else 0x0000
                    fine_y = (self._v >> 12) & 7
                    self._bg_next_tile_msb = self.ppu_read(
                        bg_table + self._bg_next_tile_id * 16 + fine_y + 8)

                elif phase == 7:
                    self._inc_scroll_x()

            # ── Al final de la scanline visible ──
            if cy == 256:
                self._inc_scroll_y()
            if cy == 257:
                self._load_bg_shifters()
                self._transfer_addr_x()

            # ── Pre-render: copiar Y desde t ──
            if sl == -1 and 280 <= cy <= 304:
                self._transfer_addr_y()

            # ── Evaluación de sprites (cy == 257) ──
            if cy == 257 and sl >= 0:
                self._evaluate_sprites()

            # ── Fetch de sprites (321-340 — simplificado aquí) ──
            if cy == 340:
                self._fetch_sprites()

        # ─── VBlank (scanline 241) ───
        if sl == 241 and cy == 1:
            self._status |= 0x80   # VBlank flag
            if self._ctrl & 0x80:   # NMI enable
                self.nmi_occurred = True

        # ─── Dibujar el píxel actual ───
        if 0 <= sl < 240 and 1 <= cy <= 256:
            self._draw_pixel(cy - 1, sl)

        # ─── Avanzar contadores ───
        self.cycle += 1
        if self.cycle >= 341:
            self.cycle = 0
            self.scanline += 1
            if self.scanline >= 261:
                self.scanline = -1
                self.frame += 1
                self.frame_ready = True
                # Copiar back buffer al framebuffer
                np.copyto(self.framebuffer, self._back_buffer)
                self._odd_frame = not self._odd_frame

    def _evaluate_sprites(self):
        """Encuentra qué sprites están en la próxima scanline."""
        self._sprite_count = 0
        self._sprite_zero_hit_possible = False

        oam_entry = 0
        for i in range(64):
            y_pos  = self.oam[oam_entry]
            offset = self.scanline - y_pos
            sprite_h = 16 if (self._ctrl & 0x20) else 8

            if 0 <= offset < sprite_h:
                if self._sprite_count < 8:
                    if i == 0:
                        self._sprite_zero_hit_possible = True
                    for b in range(4):
                        self._oam2[self._sprite_count][b] = self.oam[oam_entry + b]
                    self._sprite_count += 1
                else:
                    self._status |= 0x20   # sprite overflow
                    break
            oam_entry += 4

    def _fetch_sprites(self):
        """Carga los shift registers de sprites para la siguiente scanline."""
        sprite_h = 16 if (self._ctrl & 0x20) else 8
        spr_table = 0x1000 if (self._ctrl & 0x08) else 0x0000

        for i in range(self._sprite_count):
            sp = self._oam2[i]
            y_pos = sp[0]
            tile  = sp[1]
            attr  = sp[2]
            x_pos = sp[3]

            self._sprite_attr[i]      = attr
            self._sprite_x_counter[i] = x_pos

            row = self.scanline - y_pos
            if attr & 0x80:   # flip vertical
                row = (sprite_h - 1) - row

            if sprite_h == 8:
                addr_lo = spr_table + tile * 16 + row
            else:
                # Modo 8×16: el bit 0 del tile selecciona la tabla
                table = 0x1000 if (tile & 1) else 0x0000
                tile &= 0xFE
                if row < 8:
                    addr_lo = table + tile * 16 + row
                else:
                    addr_lo = table + (tile + 1) * 16 + (row - 8)

            lo = self.ppu_read(addr_lo)
            hi = self.ppu_read(addr_lo + 8)

            if attr & 0x40:   # flip horizontal
                lo = self._flip_byte(lo)
                hi = self._flip_byte(hi)

            self._sprite_shifter_lo[i] = lo
            self._sprite_shifter_hi[i] = hi

    @staticmethod
    def _flip_byte(b: int) -> int:
        """Invierte el orden de los bits de un byte."""
        b = ((b & 0xF0) >> 4) | ((b & 0x0F) << 4)
        b = ((b & 0xCC) >> 2) | ((b & 0x33) << 2)
        b = ((b & 0xAA) >> 1) | ((b & 0x55) << 1)
        return b & 0xFF

    def _draw_pixel(self, x: int, y: int):
        """Mezcla el pixel de background y sprite y lo escribe en el buffer."""
        bg_pixel   = 0
        bg_palette = 0

        if self._mask & 0x08:   # bg enable
            bit = 0x8000 >> self._x
            p0  = 1 if (self._bg_shifter_pattern_lo & bit) else 0
            p1  = 1 if (self._bg_shifter_pattern_hi & bit) else 0
            bg_pixel = (p1 << 1) | p0

            a0 = 1 if (self._bg_shifter_attr_lo & bit) else 0
            a1 = 1 if (self._bg_shifter_attr_hi & bit) else 0
            bg_palette = (a1 << 1) | a0

        sp_pixel   = 0
        sp_palette = 0
        sp_priority = 0
        sp_zero    = False

        if self._mask & 0x10:   # sprite enable
            self._sprite_zero_being_rendered = False
            for i in range(self._sprite_count):
                if self._sprite_x_counter[i] == 0:
                    p0 = (self._sprite_shifter_lo[i] >> 7) & 1
                    p1 = (self._sprite_shifter_hi[i] >> 7) & 1
                    sp_pixel = (p1 << 1) | p0
                    sp_palette = (self._sprite_attr[i] & 0x03) + 4
                    sp_priority = (self._sprite_attr[i] >> 5) & 1

                    if sp_pixel != 0:
                        if i == 0:
                            self._sprite_zero_being_rendered = True
                        sp_zero = (i == 0)
                        break

        # ── Decidir pixel final (prioridad BG vs sprites) ──
        pixel   = 0
        palette = 0

        if bg_pixel == 0 and sp_pixel == 0:
            pixel   = 0
            palette = 0
        elif bg_pixel == 0:
            pixel   = sp_pixel
            palette = sp_palette
        elif sp_pixel == 0:
            pixel   = bg_pixel
            palette = bg_palette
        else:
            if sp_priority == 0:   # sprite tiene prioridad
                pixel   = sp_pixel
                palette = sp_palette
            else:
                pixel   = bg_pixel
                palette = bg_palette

            # ── Sprite zero hit ──
            if (self._sprite_zero_hit_possible and
                    self._sprite_zero_being_rendered and sp_zero):
                if (self._mask & 0x08) and (self._mask & 0x10):
                    if not (self._mask & 0x02) and not (self._mask & 0x04):
                        if 9 <= x < 258:
                            self._status |= 0x40
                    else:
                        if 1 <= x < 258:
                            self._status |= 0x40

        color = self._get_color(palette, pixel)
        self._back_buffer[y, x] = color

    # ─── DMA (escribir 256 bytes a OAM) ───

    def oam_dma(self, page_data: bytes):
        """
        La CPU escribe $4014 para iniciar una transferencia DMA
        de 256 bytes hacia la OAM de la PPU.
        """
        for i, b in enumerate(page_data):
            self.oam[(self._oam_addr + i) & 0xFF] = b
