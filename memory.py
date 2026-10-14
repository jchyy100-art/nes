"""
memory.py — Bus de memoria del NES
=====================================
El NES tiene un espacio de direcciones de 16 bits (64 KB).
No toda la memoria está físicamente presente; muchas regiones
son espejos o están mapeadas a hardware específico.

Mapa de memoria de la CPU:
    $0000-$07FF  RAM interna (2 KB)
    $0800-$1FFF  Espejos de RAM (×3)
    $2000-$2007  Registros de la PPU
    $2008-$3FFF  Espejos de PPU (×1023)
    $4000-$4017  Registros de la APU y I/O
    $4018-$401F  Funciones de test (deshabilitadas)
    $4020-$FFFF  Espacio del cartucho (ROM/RAM/Mapper)
"""


class Bus:
    """
    Bus de memoria del NES.
    Conecta la CPU, PPU, APU, cartucho y controles.
    """

    # Tamaño de la RAM interna
    RAM_SIZE = 2 * 1024   # 2 KB

    def __init__(self):
        # RAM interna del NES
        self.ram = bytearray(self.RAM_SIZE)

        # Componentes (se asignan después de construir el bus)
        self.cpu  = None
        self.ppu  = None
        self.apu  = None
        self.cart = None
        self.ctrl1 = None   # Jugador 1
        self.ctrl2 = None   # Jugador 2

        # Contador de ciclos del sistema
        self._system_clock = 0

        # DMA activa
        self._dma_page    = 0x00
        self._dma_addr    = 0x00
        self._dma_data    = 0x00
        self._dma_active  = False
        self._dma_dummy   = True   # espera un ciclo antes de transferir

        # Mapper IRQ callback en caché
        self._mapper_irq = None


    # ═══════════════════════════════════════════════════════════════════════
    #                        LECTURA (CPU → BUS)
    # ═══════════════════════════════════════════════════════════════════════

    def cpu_read(self, addr: int) -> int:
        """
        La CPU pide leer un byte en la dirección addr.
        El bus determina qué componente responde.
        """
        addr &= 0xFFFF
        data = 0x00

        # ─── Cartucho (tiene prioridad en ciertas regiones) ───
        ok, val = self.cart.cpu_read(addr)
        if ok:
            return val

        # ─── RAM interna ($0000-$1FFF) con espejo ───
        if addr <= 0x1FFF:
            return self.ram[addr & 0x07FF]

        # ─── PPU ($2000-$3FFF) con espejo ───
        elif addr <= 0x3FFF:
            return self.ppu.cpu_read(addr & 0x0007)

        # ─── APU y I/O ($4000-$401F) ───
        elif addr <= 0x401F:
            if addr == 0x4015:
                return self.apu.cpu_read(addr)
            elif addr == 0x4016:
                return self.ctrl1.cpu_read() if self.ctrl1 else 0
            elif addr == 0x4017:
                return self.ctrl2.cpu_read() if self.ctrl2 else 0
            else:
                return self.apu.cpu_read(addr)

        return data

    # ═══════════════════════════════════════════════════════════════════════
    #                       ESCRITURA (CPU → BUS)
    # ═══════════════════════════════════════════════════════════════════════

    def cpu_write(self, addr: int, data: int):
        """
        La CPU escribe un byte en la dirección addr.
        """
        addr &= 0xFFFF
        data &= 0xFF

        # ─── Cartucho ───
        if self.cart.cpu_write(addr, data):
            return

        # ─── RAM interna ───
        if addr <= 0x1FFF:
            self.ram[addr & 0x07FF] = data

        # ─── PPU ───
        elif addr <= 0x3FFF:
            self.ppu.cpu_write(addr & 0x0007, data)

        # ─── APU / I/O ───
        elif addr <= 0x401F:
            if addr == 0x4014:
                # ── DMA: transferencia de 256 bytes a OAM ──
                self._dma_page   = data
                self._dma_addr   = 0x00
                self._dma_active = True
                self._dma_dummy  = True
            elif addr == 0x4016:
                # Strobe de controles
                if self.ctrl1: self.ctrl1.cpu_write(data)
                if self.ctrl2: self.ctrl2.cpu_write(data)
            else:
                self.apu.cpu_write(addr, data)

    # ═══════════════════════════════════════════════════════════════════════
    #                        CICLO DEL SISTEMA
    # ═══════════════════════════════════════════════════════════════════════

    def clock(self):
        """
        Avanza el sistema un ciclo de CPU (y 3 ciclos de PPU correspondientes).
        """
        p = self.ppu
        p.clock()
        p.clock()
        p.clock()

        if self._dma_active:
            self._handle_dma()
        else:
            self.cpu.clock()
            self.apu.clock()

            # ── Verificar IRQ del APU ──
            if self.apu.irq_pending:
                self.apu.irq_pending = False
                self.cpu.irq()

            # ── Verificar IRQ del Mapper (MMC3, etc.) ──
            if self._mapper_irq is not None and self._mapper_irq():
                self.cpu.irq()


        # ─── NMI de la PPU → CPU ───
        if p.nmi_occurred:
            p.nmi_occurred = False
            self.cpu.nmi()

        self._system_clock += 3

    def _handle_dma(self):
        """Maneja la transferencia DMA de 256 bytes a la OAM."""
        if self._dma_dummy:
            # Esperar un ciclo si es impar
            if self._system_clock % 2 == 1:
                self._dma_dummy = False
        else:
            if self._system_clock % 2 == 0:
                # Leer de la página indicada
                addr = (self._dma_page << 8) | self._dma_addr
                self._dma_data = self.cpu_read(addr)
            else:
                # Escribir en la OAM de la PPU
                self.ppu.oam[self._dma_addr] = self._dma_data
                self._dma_addr = (self._dma_addr + 1) & 0xFF
                if self._dma_addr == 0:
                    self._dma_active = False
                    self._dma_dummy  = True

    def reset(self):
        """Resetea todos los componentes del sistema."""
        self._mapper_irq = getattr(self.cart.mapper, 'irq_pending', None) if (self.cart and self.cart.mapper) else None
        if self.ppu:
            self.ppu._mapper_scanline = getattr(self.cart.mapper, 'scanline', None) if (self.cart and self.cart.mapper) else None
        self.cpu.reset()
        self.ppu.scanline = 0
        self.ppu.cycle    = 0
        self._system_clock = 0
        self._dma_active   = False
        self._dma_dummy    = True

