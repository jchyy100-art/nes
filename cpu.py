"""
cpu.py — MOS 6502 CPU (variante NES, sin modo decimal)
=======================================================
El NES usa un procesador MOS 6502 modificado. Este archivo
implementa todos los registros, modos de direccionamiento
y opcodes oficiales del chip.

Registros del 6502:
    A  — Acumulador (8 bits)
    X  — Índice X (8 bits)
    Y  — Índice Y (8 bits)
    SP — Stack Pointer (8 bits, apunta a $0100-$01FF)
    PC — Program Counter (16 bits)
    P  — Processor Status / Flags (8 bits)

Flags (P):
    N  — Negative   (bit 7)
    V  — Overflow   (bit 6)
    -  — (siempre 1)(bit 5)
    B  — Break      (bit 4)
    D  — Decimal    (bit 3, ignorado en NES)
    I  — IRQ Disable(bit 2)
    Z  — Zero       (bit 1)
    C  — Carry      (bit 0)
"""


class CPU:
    # ───────────────────────── Constantes de flags ─────────────────────────
    FLAG_C = 0x01   # Carry
    FLAG_Z = 0x02   # Zero
    FLAG_I = 0x04   # Interrupt Disable
    FLAG_D = 0x08   # Decimal (no usado en NES)
    FLAG_B = 0x10   # Break
    FLAG_U = 0x20   # Unused (siempre 1)
    FLAG_V = 0x40   # Overflow
    FLAG_N = 0x80   # Negative

    def __init__(self, bus):
        """
        bus: referencia al bus de memoria (memory.py)
              se usa para leer/escribir cualquier dirección.
        """
        self.bus = bus

        # ─── Registros ───
        self.A  = 0x00          # Acumulador
        self.X  = 0x00          # Índice X
        self.Y  = 0x00          # Índice Y
        self.SP = 0xFD          # Stack Pointer (post-reset value)
        self.PC = 0x0000        # Program Counter
        self.P  = 0x24          # Status flags (I y U siempre activos al reset)

        # Ciclos restantes del opcode actual
        self.cycles = 0

        # Ciclos totales desde el encendido
        self.total_cycles = 0

        # Variables internas usadas durante la decodificación
        self._addr_abs  = 0x0000   # Dirección absoluta calculada
        self._addr_rel  = 0x0000   # Desplazamiento relativo (para branches)
        self._fetched   = 0x00     # Dato leído en modo fetch
        self._opcode    = 0x00     # Opcode actual

        # Tabla de opcodes: índice = byte del opcode
        # Cada entrada: (nombre, función_operación, función_modo, ciclos_base)
        self._build_opcode_table()

    # ═══════════════════════════════════════════════════════════════════════
    #                        LECTURA / ESCRITURA
    # ═══════════════════════════════════════════════════════════════════════

    def read(self, addr: int) -> int:
        """Lee un byte de la dirección addr (16 bits)."""
        return self.bus.cpu_read(addr & 0xFFFF)

    def write(self, addr: int, data: int):
        """Escribe un byte en la dirección addr (16 bits)."""
        self.bus.cpu_write(addr & 0xFFFF, data & 0xFF)

    # ─── Stack helpers ───

    def _push(self, data: int):
        """Empuja un byte al stack."""
        self.write(0x0100 + self.SP, data & 0xFF)
        self.SP = (self.SP - 1) & 0xFF

    def _pop(self) -> int:
        """Saca un byte del stack."""
        self.SP = (self.SP + 1) & 0xFF
        return self.read(0x0100 + self.SP)

    def _push16(self, data: int):
        """Empuja dos bytes (high primero)."""
        self._push((data >> 8) & 0xFF)
        self._push(data & 0xFF)

    def _pop16(self) -> int:
        """Saca dos bytes (low primero)."""
        lo = self._pop()
        hi = self._pop()
        return (hi << 8) | lo

    # ─── 16-bit read ───

    def _read16(self, addr: int) -> int:
        lo = self.read(addr)
        hi = self.read((addr + 1) & 0xFFFF)
        return (hi << 8) | lo

    def _read16_wrap(self, addr: int) -> int:
        """Lee 16 bits con wrap en límite de página (bug del 6502)."""
        lo = self.read(addr)
        # El 6502 NO cruza páginas al leer el high byte del vector
        hi_addr = (addr & 0xFF00) | ((addr + 1) & 0x00FF)
        hi = self.read(hi_addr)
        return (hi << 8) | lo

    # ═══════════════════════════════════════════════════════════════════════
    #                           FLAGS
    # ═══════════════════════════════════════════════════════════════════════

    def _get_flag(self, flag: int) -> int:
        return 1 if (self.P & flag) else 0

    def _set_flag(self, flag: int, value: bool):
        if value:
            self.P |= flag
        else:
            self.P &= ~flag

    def _update_nz(self, value: int):
        """Actualiza flags N y Z según el valor (8 bits)."""
        self._set_flag(self.FLAG_Z, (value & 0xFF) == 0)
        self._set_flag(self.FLAG_N, bool(value & 0x80))

    # ═══════════════════════════════════════════════════════════════════════
    #                    MODOS DE DIRECCIONAMIENTO
    # ═══════════════════════════════════════════════════════════════════════
    # Cada función llena self._addr_abs y devuelve 1 si puede necesitar
    # un ciclo extra (cruce de página) o 0 si no.

    def _imp(self) -> int:
        """Implied — el operando es implícito (no hay dato extra)."""
        self._fetched = self.A
        return 0

    def _acc(self) -> int:
        """Accumulator — opera sobre A."""
        self._fetched = self.A
        return 0

    def _imm(self) -> int:
        """Immediate — el operando es el siguiente byte."""
        self._addr_abs = self.PC
        self.PC = (self.PC + 1) & 0xFFFF
        return 0

    def _zp0(self) -> int:
        """Zero Page — dirección en la página cero ($0000-$00FF)."""
        self._addr_abs = self.read(self.PC) & 0x00FF
        self.PC = (self.PC + 1) & 0xFFFF
        return 0

    def _zpx(self) -> int:
        """Zero Page, X — zero page + X (con wrap en $FF)."""
        self._addr_abs = (self.read(self.PC) + self.X) & 0x00FF
        self.PC = (self.PC + 1) & 0xFFFF
        return 0

    def _zpy(self) -> int:
        """Zero Page, Y — zero page + Y (con wrap en $FF)."""
        self._addr_abs = (self.read(self.PC) + self.Y) & 0x00FF
        self.PC = (self.PC + 1) & 0xFFFF
        return 0

    def _rel(self) -> int:
        """Relative — para instrucciones de branch (saltos cortos)."""
        self._addr_rel = self.read(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF
        if self._addr_rel & 0x80:          # si es negativo (complemento 2)
            self._addr_rel |= 0xFF00       # extender el signo
        return 0

    def _abs(self) -> int:
        """Absolute — dirección completa de 16 bits."""
        lo = self.read(self.PC);  self.PC = (self.PC + 1) & 0xFFFF
        hi = self.read(self.PC);  self.PC = (self.PC + 1) & 0xFFFF
        self._addr_abs = (hi << 8) | lo
        return 0

    def _abx(self) -> int:
        """Absolute, X — absoluta + X."""
        lo = self.read(self.PC);  self.PC = (self.PC + 1) & 0xFFFF
        hi = self.read(self.PC);  self.PC = (self.PC + 1) & 0xFFFF
        self._addr_abs = ((hi << 8) | lo) + self.X
        # Ciclo extra si cruzamos página
        if (self._addr_abs & 0xFF00) != (hi << 8):
            return 1
        return 0

    def _aby(self) -> int:
        """Absolute, Y — absoluta + Y."""
        lo = self.read(self.PC);  self.PC = (self.PC + 1) & 0xFFFF
        hi = self.read(self.PC);  self.PC = (self.PC + 1) & 0xFFFF
        self._addr_abs = ((hi << 8) | lo) + self.Y
        if (self._addr_abs & 0xFF00) != (hi << 8):
            return 1
        return 0

    def _ind(self) -> int:
        """Indirect — JMP ($NNNN). Tiene el bug del 6502 en límite de página."""
        lo = self.read(self.PC);  self.PC = (self.PC + 1) & 0xFFFF
        hi = self.read(self.PC);  self.PC = (self.PC + 1) & 0xFFFF
        ptr = (hi << 8) | lo
        self._addr_abs = self._read16_wrap(ptr)
        return 0

    def _izx(self) -> int:
        """(Indirect, X) — La dirección de la tabla está en zero page + X."""
        t = self.read(self.PC);  self.PC = (self.PC + 1) & 0xFFFF
        lo = self.read((t + self.X) & 0x00FF)
        hi = self.read((t + self.X + 1) & 0x00FF)
        self._addr_abs = (hi << 8) | lo
        return 0

    def _izy(self) -> int:
        """(Indirect), Y — La dirección base está en zero page, luego +Y."""
        t = self.read(self.PC);  self.PC = (self.PC + 1) & 0xFFFF
        lo = self.read(t & 0x00FF)
        hi = self.read((t + 1) & 0x00FF)
        self._addr_abs = ((hi << 8) | lo) + self.Y
        if (self._addr_abs & 0xFF00) != (hi << 8):
            return 1
        return 0

    # ─── fetch: lee el operando según el modo ───

    def _fetch(self) -> int:
        if self._lookup[self._opcode][2] != self._imp:
            self._fetched = self.read(self._addr_abs)
        return self._fetched

    # ═══════════════════════════════════════════════════════════════════════
    #                           INSTRUCCIONES
    # ═══════════════════════════════════════════════════════════════════════

    # ─── Aritméticas ───

    def _ADC(self) -> int:
        self._fetch()
        tmp = self.A + self._fetched + self._get_flag(self.FLAG_C)
        self._set_flag(self.FLAG_C, tmp > 0xFF)
        self._set_flag(self.FLAG_V,
            bool((~(self.A ^ self._fetched) & (self.A ^ tmp)) & 0x80))
        self._update_nz(tmp)
        self.A = tmp & 0xFF
        return 1

    def _SBC(self) -> int:
        self._fetch()
        value = self._fetched ^ 0xFF
        tmp = self.A + value + self._get_flag(self.FLAG_C)
        self._set_flag(self.FLAG_C, tmp > 0xFF)
        self._set_flag(self.FLAG_V,
            bool(((tmp ^ self.A) & (tmp ^ value)) & 0x80))
        self._update_nz(tmp)
        self.A = tmp & 0xFF
        return 1

    # ─── Lógicas ───

    def _AND(self) -> int:
        self._fetch()
        self.A &= self._fetched
        self._update_nz(self.A)
        return 1

    def _ORA(self) -> int:
        self._fetch()
        self.A |= self._fetched
        self._update_nz(self.A)
        return 1

    def _EOR(self) -> int:
        self._fetch()
        self.A ^= self._fetched
        self._update_nz(self.A)
        return 1

    def _BIT(self) -> int:
        self._fetch()
        tmp = self.A & self._fetched
        self._set_flag(self.FLAG_Z, (tmp & 0xFF) == 0)
        self._set_flag(self.FLAG_N, bool(self._fetched & self.FLAG_N))
        self._set_flag(self.FLAG_V, bool(self._fetched & self.FLAG_V))
        return 0

    # ─── Shifts / Rotaciones ───

    def _ASL(self) -> int:
        self._fetch()
        tmp = self._fetched << 1
        self._set_flag(self.FLAG_C, bool(self._fetched & 0x80))
        self._update_nz(tmp)
        if self._lookup[self._opcode][2] == self._imp:
            self.A = tmp & 0xFF
        else:
            self.write(self._addr_abs, tmp & 0xFF)
        return 0

    def _LSR(self) -> int:
        self._fetch()
        self._set_flag(self.FLAG_C, bool(self._fetched & 0x01))
        tmp = self._fetched >> 1
        self._update_nz(tmp)
        if self._lookup[self._opcode][2] == self._imp:
            self.A = tmp & 0xFF
        else:
            self.write(self._addr_abs, tmp & 0xFF)
        return 0

    def _ROL(self) -> int:
        self._fetch()
        tmp = (self._fetched << 1) | self._get_flag(self.FLAG_C)
        self._set_flag(self.FLAG_C, bool(self._fetched & 0x80))
        self._update_nz(tmp)
        if self._lookup[self._opcode][2] == self._imp:
            self.A = tmp & 0xFF
        else:
            self.write(self._addr_abs, tmp & 0xFF)
        return 0

    def _ROR(self) -> int:
        self._fetch()
        tmp = (self._get_flag(self.FLAG_C) << 7) | (self._fetched >> 1)
        self._set_flag(self.FLAG_C, bool(self._fetched & 0x01))
        self._update_nz(tmp)
        if self._lookup[self._opcode][2] == self._imp:
            self.A = tmp & 0xFF
        else:
            self.write(self._addr_abs, tmp & 0xFF)
        return 0

    # ─── Incremento / Decremento ───

    def _INC(self) -> int:
        self._fetch()
        tmp = (self._fetched + 1) & 0xFF
        self._update_nz(tmp)
        self.write(self._addr_abs, tmp)
        return 0

    def _DEC(self) -> int:
        self._fetch()
        tmp = (self._fetched - 1) & 0xFF
        self._update_nz(tmp)
        self.write(self._addr_abs, tmp)
        return 0

    def _INX(self) -> int:
        self.X = (self.X + 1) & 0xFF
        self._update_nz(self.X)
        return 0

    def _INY(self) -> int:
        self.Y = (self.Y + 1) & 0xFF
        self._update_nz(self.Y)
        return 0

    def _DEX(self) -> int:
        self.X = (self.X - 1) & 0xFF
        self._update_nz(self.X)
        return 0

    def _DEY(self) -> int:
        self.Y = (self.Y - 1) & 0xFF
        self._update_nz(self.Y)
        return 0

    # ─── Comparaciones ───

    def _compare(self, reg: int) -> int:
        self._fetch()
        tmp = reg - self._fetched
        self._set_flag(self.FLAG_C, reg >= self._fetched)
        self._update_nz(tmp)
        return 1

    def _CMP(self) -> int: return self._compare(self.A)
    def _CPX(self) -> int: return self._compare(self.X)
    def _CPY(self) -> int: return self._compare(self.Y)

    # ─── Carga ───

    def _LDA(self) -> int:
        self._fetch()
        self.A = self._fetched
        self._update_nz(self.A)
        return 1

    def _LDX(self) -> int:
        self._fetch()
        self.X = self._fetched
        self._update_nz(self.X)
        return 1

    def _LDY(self) -> int:
        self._fetch()
        self.Y = self._fetched
        self._update_nz(self.Y)
        return 1

    # ─── Almacenamiento ───

    def _STA(self) -> int:
        self.write(self._addr_abs, self.A)
        return 0

    def _STX(self) -> int:
        self.write(self._addr_abs, self.X)
        return 0

    def _STY(self) -> int:
        self.write(self._addr_abs, self.Y)
        return 0

    # ─── Transferencias ───

    def _TAX(self) -> int:
        self.X = self.A; self._update_nz(self.X); return 0

    def _TAY(self) -> int:
        self.Y = self.A; self._update_nz(self.Y); return 0

    def _TXA(self) -> int:
        self.A = self.X; self._update_nz(self.A); return 0

    def _TYA(self) -> int:
        self.A = self.Y; self._update_nz(self.A); return 0

    def _TSX(self) -> int:
        self.X = self.SP; self._update_nz(self.X); return 0

    def _TXS(self) -> int:
        self.SP = self.X; return 0

    # ─── Stack ───

    def _PHA(self) -> int:
        self._push(self.A); return 0

    def _PHP(self) -> int:
        self._push(self.P | self.FLAG_B | self.FLAG_U); return 0

    def _PLA(self) -> int:
        self.A = self._pop(); self._update_nz(self.A); return 0

    def _PLP(self) -> int:
        self.P = self._pop()
        self._set_flag(self.FLAG_U, True)
        return 0

    # ─── Saltos ───

    def _JMP(self) -> int:
        self.PC = self._addr_abs; return 0

    def _JSR(self) -> int:
        # Guarda la dirección de retorno - 1
        self._push16((self.PC - 1) & 0xFFFF)
        self.PC = self._addr_abs
        return 0

    def _RTS(self) -> int:
        self.PC = (self._pop16() + 1) & 0xFFFF; return 0

    def _RTI(self) -> int:
        self.P = self._pop()
        self._set_flag(self.FLAG_B, False)
        self._set_flag(self.FLAG_U, True)
        self.PC = self._pop16()
        return 0

    # ─── Branches (saltos condicionales) ───

    def _branch(self, condition: bool) -> int:
        if condition:
            self.cycles += 1
            new_pc = (self.PC + self._addr_rel) & 0xFFFF
            if (new_pc & 0xFF00) != (self.PC & 0xFF00):
                self.cycles += 1  # ciclo extra por cruce de página
            self.PC = new_pc
        return 0

    def _BCC(self) -> int: return self._branch(not self._get_flag(self.FLAG_C))
    def _BCS(self) -> int: return self._branch(bool(self._get_flag(self.FLAG_C)))
    def _BNE(self) -> int: return self._branch(not self._get_flag(self.FLAG_Z))
    def _BEQ(self) -> int: return self._branch(bool(self._get_flag(self.FLAG_Z)))
    def _BPL(self) -> int: return self._branch(not self._get_flag(self.FLAG_N))
    def _BMI(self) -> int: return self._branch(bool(self._get_flag(self.FLAG_N)))
    def _BVC(self) -> int: return self._branch(not self._get_flag(self.FLAG_V))
    def _BVS(self) -> int: return self._branch(bool(self._get_flag(self.FLAG_V)))

    # ─── Flags de control ───

    def _CLC(self) -> int: self._set_flag(self.FLAG_C, False); return 0
    def _SEC(self) -> int: self._set_flag(self.FLAG_C, True);  return 0
    def _CLI(self) -> int: self._set_flag(self.FLAG_I, False); return 0
    def _SEI(self) -> int: self._set_flag(self.FLAG_I, True);  return 0
    def _CLV(self) -> int: self._set_flag(self.FLAG_V, False); return 0
    def _CLD(self) -> int: self._set_flag(self.FLAG_D, False); return 0
    def _SED(self) -> int: self._set_flag(self.FLAG_D, True);  return 0

    # ─── Interrupciones y NOP ───

    def _NOP(self) -> int: return 0

    def _BRK(self) -> int:
        self.PC = (self.PC + 1) & 0xFFFF
        self._set_flag(self.FLAG_I, True)
        self._push16(self.PC)
        self._push(self.P | self.FLAG_B | self.FLAG_U)
        self._set_flag(self.FLAG_B, False)
        self.PC = self._read16(0xFFFE)
        return 0

    def _XXX(self) -> int:
        """Opcode ilegal / no implementado — se ignora."""
        return 0

    # ═══════════════════════════════════════════════════════════════════════
    #                    TABLA DE OPCODES (256 entradas)
    # ═══════════════════════════════════════════════════════════════════════

    def _build_opcode_table(self):
        """
        Formato de cada fila:
            (nombre_str, func_operacion, func_modo_dir, ciclos_base)
        """
        X = self._XXX   # atajo para ilegales

        self._lookup = [
            # 0x00-0x0F
            ("BRK", self._BRK, self._imp, 7), ("ORA", self._ORA, self._izx, 6),
            ("???", X,         self._imp, 2), ("???", X, self._imp, 8),
            ("???", self._NOP, self._zp0, 3), ("ORA", self._ORA, self._zp0, 3),
            ("ASL", self._ASL, self._zp0, 5), ("???", X, self._imp, 5),
            ("PHP", self._PHP, self._imp, 3), ("ORA", self._ORA, self._imm, 2),
            ("ASL", self._ASL, self._imp, 2), ("???", X, self._imp, 2),
            ("???", self._NOP, self._abs, 4), ("ORA", self._ORA, self._abs, 4),
            ("ASL", self._ASL, self._abs, 6), ("???", X, self._imp, 6),
            # 0x10-0x1F
            ("BPL", self._BPL, self._rel, 2), ("ORA", self._ORA, self._izy, 5),
            ("???", X, self._imp, 2), ("???", X, self._imp, 8),
            ("???", self._NOP, self._zpx, 4), ("ORA", self._ORA, self._zpx, 4),
            ("ASL", self._ASL, self._zpx, 6), ("???", X, self._imp, 6),
            ("CLC", self._CLC, self._imp, 2), ("ORA", self._ORA, self._aby, 4),
            ("???", self._NOP, self._imp, 2), ("???", X, self._imp, 7),
            ("???", self._NOP, self._abx, 4), ("ORA", self._ORA, self._abx, 4),
            ("ASL", self._ASL, self._abx, 7), ("???", X, self._imp, 7),
            # 0x20-0x2F
            ("JSR", self._JSR, self._abs, 6), ("AND", self._AND, self._izx, 6),
            ("???", X, self._imp, 2), ("???", X, self._imp, 8),
            ("BIT", self._BIT, self._zp0, 3), ("AND", self._AND, self._zp0, 3),
            ("ROL", self._ROL, self._zp0, 5), ("???", X, self._imp, 5),
            ("PLP", self._PLP, self._imp, 4), ("AND", self._AND, self._imm, 2),
            ("ROL", self._ROL, self._imp, 2), ("???", X, self._imp, 2),
            ("BIT", self._BIT, self._abs, 4), ("AND", self._AND, self._abs, 4),
            ("ROL", self._ROL, self._abs, 6), ("???", X, self._imp, 6),
            # 0x30-0x3F
            ("BMI", self._BMI, self._rel, 2), ("AND", self._AND, self._izy, 5),
            ("???", X, self._imp, 2), ("???", X, self._imp, 8),
            ("???", self._NOP, self._zpx, 4), ("AND", self._AND, self._zpx, 4),
            ("ROL", self._ROL, self._zpx, 6), ("???", X, self._imp, 6),
            ("SEC", self._SEC, self._imp, 2), ("AND", self._AND, self._aby, 4),
            ("???", self._NOP, self._imp, 2), ("???", X, self._imp, 7),
            ("???", self._NOP, self._abx, 4), ("AND", self._AND, self._abx, 4),
            ("ROL", self._ROL, self._abx, 7), ("???", X, self._imp, 7),
            # 0x40-0x4F
            ("RTI", self._RTI, self._imp, 6), ("EOR", self._EOR, self._izx, 6),
            ("???", X, self._imp, 2), ("???", X, self._imp, 8),
            ("???", self._NOP, self._zp0, 3), ("EOR", self._EOR, self._zp0, 3),
            ("LSR", self._LSR, self._zp0, 5), ("???", X, self._imp, 5),
            ("PHA", self._PHA, self._imp, 3), ("EOR", self._EOR, self._imm, 2),
            ("LSR", self._LSR, self._imp, 2), ("???", X, self._imp, 2),
            ("JMP", self._JMP, self._abs, 3), ("EOR", self._EOR, self._abs, 4),
            ("LSR", self._LSR, self._abs, 6), ("???", X, self._imp, 6),
            # 0x50-0x5F
            ("BVC", self._BVC, self._rel, 2), ("EOR", self._EOR, self._izy, 5),
            ("???", X, self._imp, 2), ("???", X, self._imp, 8),
            ("???", self._NOP, self._zpx, 4), ("EOR", self._EOR, self._zpx, 4),
            ("LSR", self._LSR, self._zpx, 6), ("???", X, self._imp, 6),
            ("CLI", self._CLI, self._imp, 2), ("EOR", self._EOR, self._aby, 4),
            ("???", self._NOP, self._imp, 2), ("???", X, self._imp, 7),
            ("???", self._NOP, self._abx, 4), ("EOR", self._EOR, self._abx, 4),
            ("LSR", self._LSR, self._abx, 7), ("???", X, self._imp, 7),
            # 0x60-0x6F
            ("RTS", self._RTS, self._imp, 6), ("ADC", self._ADC, self._izx, 6),
            ("???", X, self._imp, 2), ("???", X, self._imp, 8),
            ("???", self._NOP, self._zp0, 3), ("ADC", self._ADC, self._zp0, 3),
            ("ROR", self._ROR, self._zp0, 5), ("???", X, self._imp, 5),
            ("PLA", self._PLA, self._imp, 4), ("ADC", self._ADC, self._imm, 2),
            ("ROR", self._ROR, self._imp, 2), ("???", X, self._imp, 2),
            ("JMP", self._JMP, self._ind, 5), ("ADC", self._ADC, self._abs, 4),
            ("ROR", self._ROR, self._abs, 6), ("???", X, self._imp, 6),
            # 0x70-0x7F
            ("BVS", self._BVS, self._rel, 2), ("ADC", self._ADC, self._izy, 5),
            ("???", X, self._imp, 2), ("???", X, self._imp, 8),
            ("???", self._NOP, self._zpx, 4), ("ADC", self._ADC, self._zpx, 4),
            ("ROR", self._ROR, self._zpx, 6), ("???", X, self._imp, 6),
            ("SEI", self._SEI, self._imp, 2), ("ADC", self._ADC, self._aby, 4),
            ("???", self._NOP, self._imp, 2), ("???", X, self._imp, 7),
            ("???", self._NOP, self._abx, 4), ("ADC", self._ADC, self._abx, 4),
            ("ROR", self._ROR, self._abx, 7), ("???", X, self._imp, 7),
            # 0x80-0x8F
            ("???", self._NOP, self._imm, 2), ("STA", self._STA, self._izx, 6),
            ("???", self._NOP, self._imm, 2), ("???", X, self._imp, 6),
            ("STY", self._STY, self._zp0, 3), ("STA", self._STA, self._zp0, 3),
            ("STX", self._STX, self._zp0, 3), ("???", X, self._imp, 3),
            ("DEY", self._DEY, self._imp, 2), ("???", self._NOP, self._imm, 2),
            ("TXA", self._TXA, self._imp, 2), ("???", X, self._imp, 2),
            ("STY", self._STY, self._abs, 4), ("STA", self._STA, self._abs, 4),
            ("STX", self._STX, self._abs, 4), ("???", X, self._imp, 4),
            # 0x90-0x9F
            ("BCC", self._BCC, self._rel, 2), ("STA", self._STA, self._izy, 6),
            ("???", X, self._imp, 2), ("???", X, self._imp, 6),
            ("STY", self._STY, self._zpx, 4), ("STA", self._STA, self._zpx, 4),
            ("STX", self._STX, self._zpy, 4), ("???", X, self._imp, 4),
            ("TYA", self._TYA, self._imp, 2), ("STA", self._STA, self._aby, 5),
            ("TXS", self._TXS, self._imp, 2), ("???", X, self._imp, 5),
            ("???", self._NOP, self._abx, 5), ("STA", self._STA, self._abx, 5),
            ("???", X, self._imp, 5), ("???", X, self._imp, 5),
            # 0xA0-0xAF
            ("LDY", self._LDY, self._imm, 2), ("LDA", self._LDA, self._izx, 6),
            ("LDX", self._LDX, self._imm, 2), ("???", X, self._imp, 6),
            ("LDY", self._LDY, self._zp0, 3), ("LDA", self._LDA, self._zp0, 3),
            ("LDX", self._LDX, self._zp0, 3), ("???", X, self._imp, 3),
            ("TAY", self._TAY, self._imp, 2), ("LDA", self._LDA, self._imm, 2),
            ("TAX", self._TAX, self._imp, 2), ("???", X, self._imp, 2),
            ("LDY", self._LDY, self._abs, 4), ("LDA", self._LDA, self._abs, 4),
            ("LDX", self._LDX, self._abs, 4), ("???", X, self._imp, 4),
            # 0xB0-0xBF
            ("BCS", self._BCS, self._rel, 2), ("LDA", self._LDA, self._izy, 5),
            ("???", X, self._imp, 2), ("???", X, self._imp, 5),
            ("LDY", self._LDY, self._zpx, 4), ("LDA", self._LDA, self._zpx, 4),
            ("LDX", self._LDX, self._zpy, 4), ("???", X, self._imp, 4),
            ("CLV", self._CLV, self._imp, 2), ("LDA", self._LDA, self._aby, 4),
            ("TSX", self._TSX, self._imp, 2), ("???", X, self._imp, 4),
            ("LDY", self._LDY, self._abx, 4), ("LDA", self._LDA, self._abx, 4),
            ("LDX", self._LDX, self._aby, 4), ("???", X, self._imp, 4),
            # 0xC0-0xCF
            ("CPY", self._CPY, self._imm, 2), ("CMP", self._CMP, self._izx, 6),
            ("???", self._NOP, self._imm, 2), ("???", X, self._imp, 8),
            ("CPY", self._CPY, self._zp0, 3), ("CMP", self._CMP, self._zp0, 3),
            ("DEC", self._DEC, self._zp0, 5), ("???", X, self._imp, 5),
            ("INY", self._INY, self._imp, 2), ("CMP", self._CMP, self._imm, 2),
            ("DEX", self._DEX, self._imp, 2), ("???", X, self._imp, 2),
            ("CPY", self._CPY, self._abs, 4), ("CMP", self._CMP, self._abs, 4),
            ("DEC", self._DEC, self._abs, 6), ("???", X, self._imp, 6),
            # 0xD0-0xDF
            ("BNE", self._BNE, self._rel, 2), ("CMP", self._CMP, self._izy, 5),
            ("???", X, self._imp, 2), ("???", X, self._imp, 8),
            ("???", self._NOP, self._zpx, 4), ("CMP", self._CMP, self._zpx, 4),
            ("DEC", self._DEC, self._zpx, 6), ("???", X, self._imp, 6),
            ("CLD", self._CLD, self._imp, 2), ("CMP", self._CMP, self._aby, 4),
            ("???", self._NOP, self._imp, 2), ("???", X, self._imp, 7),
            ("???", self._NOP, self._abx, 4), ("CMP", self._CMP, self._abx, 4),
            ("DEC", self._DEC, self._abx, 7), ("???", X, self._imp, 7),
            # 0xE0-0xEF
            ("CPX", self._CPX, self._imm, 2), ("SBC", self._SBC, self._izx, 6),
            ("???", self._NOP, self._imm, 2), ("???", X, self._imp, 8),
            ("CPX", self._CPX, self._zp0, 3), ("SBC", self._SBC, self._zp0, 3),
            ("INC", self._INC, self._zp0, 5), ("???", X, self._imp, 5),
            ("INX", self._INX, self._imp, 2), ("SBC", self._SBC, self._imm, 2),
            ("NOP", self._NOP, self._imp, 2), ("???", X, self._imp, 2),
            ("CPX", self._CPX, self._abs, 4), ("SBC", self._SBC, self._abs, 4),
            ("INC", self._INC, self._abs, 6), ("???", X, self._imp, 6),
            # 0xF0-0xFF
            ("BEQ", self._BEQ, self._rel, 2), ("SBC", self._SBC, self._izy, 5),
            ("???", X, self._imp, 2), ("???", X, self._imp, 8),
            ("???", self._NOP, self._zpx, 4), ("SBC", self._SBC, self._zpx, 4),
            ("INC", self._INC, self._zpx, 6), ("???", X, self._imp, 6),
            ("SED", self._SED, self._imp, 2), ("SBC", self._SBC, self._aby, 4),
            ("???", self._NOP, self._imp, 2), ("???", X, self._imp, 7),
            ("???", self._NOP, self._abx, 4), ("SBC", self._SBC, self._abx, 4),
            ("INC", self._INC, self._abx, 7), ("???", X, self._imp, 7),
        ]

    # ═══════════════════════════════════════════════════════════════════════
    #                        CICLO PRINCIPAL
    # ═══════════════════════════════════════════════════════════════════════

    def clock(self):
        """
        Avanza la CPU un ciclo de reloj.
        El 6502 tarda varios ciclos por instrucción; aquí simulamos
        esto consumiendo ciclos y ejecutando la instrucción completa
        cuando el contador llega a 0.
        """
        if self.cycles == 0:
            # Leer el opcode
            self._opcode = self.read(self.PC)
            self.PC = (self.PC + 1) & 0xFFFF

            # Aseguramos U siempre encendido
            self._set_flag(self.FLAG_U, True)

            # Obtener la entrada de la tabla
            entry = self._lookup[self._opcode]
            self.cycles = entry[3]            # ciclos base

            # Ejecutar modo de direccionamiento
            extra1 = entry[2]()               # función de modo

            # Ejecutar la operación
            extra2 = entry[1]()               # función de operación

            # Ambos devuelven 1 si pueden necesitar ciclo extra
            self.cycles += extra1 & extra2

            self._set_flag(self.FLAG_U, True)

        self.cycles -= 1
        self.total_cycles += 1

    # ─── Interrupciones ───

    def reset(self):
        """Reset del sistema — equivalente a encender el NES."""
        self.A  = 0
        self.X  = 0
        self.Y  = 0
        self.SP = 0xFD
        self.P  = 0x24

        # El vector de reset está en $FFFC/$FFFD
        self.PC = self._read16(0xFFFC)

        self._addr_abs = 0
        self._addr_rel = 0
        self._fetched  = 0

        self.cycles = 8   # El reset tarda 8 ciclos

    def irq(self):
        """Interrupción enmascarable (IRQ)."""
        if self._get_flag(self.FLAG_I) == 0:
            self._push16(self.PC)
            self._set_flag(self.FLAG_B, False)
            self._set_flag(self.FLAG_U, True)
            self._set_flag(self.FLAG_I, True)
            self._push(self.P)
            self.PC = self._read16(0xFFFE)
            self.cycles = 7

    def nmi(self):
        """Interrupción no enmascarable (NMI) — usada por la PPU."""
        self._push16(self.PC)
        self._set_flag(self.FLAG_B, False)
        self._set_flag(self.FLAG_U, True)
        self._set_flag(self.FLAG_I, True)
        self._push(self.P)
        self.PC = self._read16(0xFFFA)
        self.cycles = 8

    def is_complete(self) -> bool:
        """True cuando la instrucción actual terminó de ejecutarse."""
        return self.cycles == 0
