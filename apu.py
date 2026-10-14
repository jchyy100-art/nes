"""
apu.py — Audio Processing Unit (APU) del NES
==============================================
El NES genera audio mediante 5 canales:
    1. Pulse 1   — Onda cuadrada (voz 1)
    2. Pulse 2   — Onda cuadrada (voz 2)
    3. Triangle  — Onda triangular
    4. Noise     — Ruido pseudo-aleatorio
    5. DMC       — Delta Modulation Channel (samples PCM)

Registros de la APU ($4000-$4017):
    $4000-$4003: Pulse 1
    $4004-$4007: Pulse 2
    $4008-$400B: Triangle
    $400C-$400F: Noise
    $4010-$4013: DMC
    $4015:       Status (enable/disable canales)
    $4017:       Frame counter

Este módulo usa pygame.mixer para reproducir audio
generando muestras PCM en tiempo real.
"""

import numpy as np


# ─── Tablas de longitud del NES ──────────────────────────────────────────────
LENGTH_TABLE = [
    10, 254, 20, 2, 40, 4, 80, 6, 160, 8, 60, 10, 14, 12, 26, 14,
    12, 16, 24, 18, 48, 20, 96, 22, 192, 24, 72, 26, 16, 28, 32, 30,
]

# Tabla de frecuencias del canal de ruido
NOISE_PERIOD_TABLE = [
    4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068,
]

# Tabla de tasas del DMC
DMC_RATE_TABLE = [
    428, 380, 340, 320, 286, 254, 226, 214, 190, 160, 142, 128, 106, 84, 72, 54,
]

# Secuencias de ciclo de trabajo de los canales pulse
DUTY_TABLE = [
    [0, 1, 0, 0, 0, 0, 0, 0],  # 12.5%
    [0, 1, 1, 0, 0, 0, 0, 0],  # 25%
    [0, 1, 1, 1, 1, 0, 0, 0],  # 50%
    [1, 0, 0, 1, 1, 1, 1, 1],  # 25% negado
]


class Envelope:
    """Generador de envolvente de volumen."""
    def __init__(self):
        self.start    = False
        self.loop     = False
        self.constant = False
        self.volume   = 0
        self.decay    = 0
        self.divider  = 0

    def clock(self):
        if self.start:
            self.start  = False
            self.decay  = 15
            self.divider = self.volume
        else:
            if self.divider > 0:
                self.divider -= 1
            else:
                self.divider = self.volume
                if self.decay > 0:
                    self.decay -= 1
                elif self.loop:
                    self.decay = 15

    @property
    def output(self) -> int:
        return self.volume if self.constant else self.decay


class PulseChannel:
    """Canal de onda cuadrada (Pulse 1 y Pulse 2)."""
    def __init__(self, is_pulse2: bool = False):
        self.is_pulse2    = is_pulse2
        self.enabled      = False
        self.duty_mode    = 0
        self.duty_value   = 0
        self.length_halt  = False
        self.length_value = 0
        self.timer_period = 0
        self.timer_value  = 0
        self.sweep_enabled  = False
        self.sweep_period   = 0
        self.sweep_negate   = False
        self.sweep_shift    = 0
        self.sweep_reload   = False
        self.sweep_value    = 0
        self.envelope = Envelope()

    def write_ctrl(self, data: int):
        self.duty_mode    = (data >> 6) & 3
        self.length_halt  = bool(data & 0x20)
        self.envelope.loop      = bool(data & 0x20)
        self.envelope.constant  = bool(data & 0x10)
        self.envelope.volume    = data & 0x0F

    def write_sweep(self, data: int):
        self.sweep_enabled = bool(data & 0x80)
        self.sweep_period  = (data >> 4) & 7
        self.sweep_negate  = bool(data & 0x08)
        self.sweep_shift   = data & 0x07
        self.sweep_reload  = True

    def write_lo(self, data: int):
        self.timer_period = (self.timer_period & 0xFF00) | data

    def write_hi(self, data: int):
        self.timer_period  = (self.timer_period & 0x00FF) | ((data & 7) << 8)
        self.length_value  = LENGTH_TABLE[(data >> 3) & 0x1F]
        self.duty_value    = 0
        self.envelope.start = True

    def clock_timer(self):
        if self.timer_value == 0:
            self.timer_value = self.timer_period
            self.duty_value  = (self.duty_value + 1) & 7
        else:
            self.timer_value -= 1

    def clock_length(self):
        if not self.length_halt and self.length_value > 0:
            self.length_value -= 1

    def clock_sweep(self):
        if self.sweep_reload:
            self.sweep_value  = self.sweep_period
            self.sweep_reload = False
        elif self.sweep_value > 0:
            self.sweep_value -= 1
        else:
            self.sweep_value = self.sweep_period
            if self.sweep_enabled and self.sweep_shift > 0:
                delta = self.timer_period >> self.sweep_shift
                if self.sweep_negate:
                    self.timer_period -= delta
                    if self.is_pulse2:
                        self.timer_period -= 1
                else:
                    self.timer_period += delta

    def _is_muted(self) -> bool:
        return (self.timer_period < 8 or
                self.timer_period > 0x7FF or
                self.length_value == 0)

    @property
    def output(self) -> float:
        if not self.enabled or self._is_muted():
            return 0.0
        seq = DUTY_TABLE[self.duty_mode][self.duty_value]
        return seq * self.envelope.output / 15.0


class TriangleChannel:
    """Canal de onda triangular."""
    SEQUENCE = [15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0,
                0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]

    def __init__(self):
        self.enabled       = False
        self.length_halt   = False
        self.length_value  = 0
        self.linear_period = 0
        self.linear_value  = 0
        self.linear_reload = False
        self.timer_period  = 0
        self.timer_value   = 0
        self.duty_value    = 0

    def write_ctrl(self, data: int):
        self.length_halt   = bool(data & 0x80)
        self.linear_period = data & 0x7F

    def write_lo(self, data: int):
        self.timer_period = (self.timer_period & 0xFF00) | data

    def write_hi(self, data: int):
        self.timer_period  = (self.timer_period & 0x00FF) | ((data & 7) << 8)
        self.length_value  = LENGTH_TABLE[(data >> 3) & 0x1F]
        self.linear_reload = True

    def clock_timer(self):
        if self.timer_value == 0:
            self.timer_value = self.timer_period
            if self.length_value > 0 and self.linear_value > 0:
                self.duty_value = (self.duty_value + 1) % 32
        else:
            self.timer_value -= 1

    def clock_length(self):
        if not self.length_halt and self.length_value > 0:
            self.length_value -= 1

    def clock_linear(self):
        if self.linear_reload:
            self.linear_value = self.linear_period
        elif self.linear_value > 0:
            self.linear_value -= 1
        if not self.length_halt:
            self.linear_reload = False

    @property
    def output(self) -> float:
        if not self.enabled or self.length_value == 0 or self.linear_value == 0:
            return 0.0
        return self.SEQUENCE[self.duty_value] / 15.0


class NoiseChannel:
    """Canal de ruido pseudo-aleatorio."""
    def __init__(self):
        self.enabled      = False
        self.mode         = False
        self.shift_reg    = 1
        self.length_halt  = False
        self.length_value = 0
        self.timer_period = NOISE_PERIOD_TABLE[0]
        self.timer_value  = 0
        self.envelope     = Envelope()

    def write_ctrl(self, data: int):
        self.length_halt       = bool(data & 0x20)
        self.envelope.loop     = bool(data & 0x20)
        self.envelope.constant = bool(data & 0x10)
        self.envelope.volume   = data & 0x0F

    def write_period(self, data: int):
        self.mode         = bool(data & 0x80)
        self.timer_period = NOISE_PERIOD_TABLE[data & 0x0F]

    def write_length(self, data: int):
        self.length_value   = LENGTH_TABLE[(data >> 3) & 0x1F]
        self.envelope.start = True

    def clock_timer(self):
        if self.timer_value == 0:
            self.timer_value = self.timer_period
            bit = 6 if self.mode else 1
            feedback = ((self.shift_reg ^ (self.shift_reg >> bit)) & 1) << 14
            self.shift_reg = (self.shift_reg >> 1) | feedback
        else:
            self.timer_value -= 1

    def clock_length(self):
        if not self.length_halt and self.length_value > 0:
            self.length_value -= 1

    @property
    def output(self) -> float:
        if not self.enabled or self.length_value == 0 or (self.shift_reg & 1):
            return 0.0
        return self.envelope.output / 15.0


class APU:
    """
    APU del NES.
    Genera muestras de audio que se entregan a pygame.
    """

    SAMPLE_RATE   = 44100
    CPU_FREQ      = 1789773   # Hz (NTSC)

    def __init__(self, bus):
        self.bus     = bus
        self.pulse1  = PulseChannel(is_pulse2=False)
        self.pulse2  = PulseChannel(is_pulse2=True)
        self.triangle = TriangleChannel()
        self.noise   = NoiseChannel()

        self._frame_counter = 0
        self._frame_mode    = 0    # 0=4-step, 1=5-step
        self._frame_irq     = False
        self._irq_inhibit   = False

        # Ratio de downsampling CPU→audio
        self._clock_count  = 0
        self._sample_accum = 0.0
        self._sample_count = 0

        # Buffer de muestras para pygame
        self._sample_buffer = []
        self._buffer_limit  = self.SAMPLE_RATE // 30   # 2 frames de audio

        self.irq_pending = False

    # ─── Escritura de registros ───

    def cpu_write(self, addr: int, data: int):
        if addr == 0x4000: self.pulse1.write_ctrl(data)
        elif addr == 0x4001: self.pulse1.write_sweep(data)
        elif addr == 0x4002: self.pulse1.write_lo(data)
        elif addr == 0x4003: self.pulse1.write_hi(data)
        elif addr == 0x4004: self.pulse2.write_ctrl(data)
        elif addr == 0x4005: self.pulse2.write_sweep(data)
        elif addr == 0x4006: self.pulse2.write_lo(data)
        elif addr == 0x4007: self.pulse2.write_hi(data)
        elif addr == 0x4008: self.triangle.write_ctrl(data)
        elif addr == 0x400A: self.triangle.write_lo(data)
        elif addr == 0x400B: self.triangle.write_hi(data)
        elif addr == 0x400C: self.noise.write_ctrl(data)
        elif addr == 0x400E: self.noise.write_period(data)
        elif addr == 0x400F: self.noise.write_length(data)
        elif addr == 0x4015:
            self.pulse1.enabled   = bool(data & 0x01)
            self.pulse2.enabled   = bool(data & 0x02)
            self.triangle.enabled = bool(data & 0x04)
            self.noise.enabled    = bool(data & 0x08)
            if not self.pulse1.enabled:   self.pulse1.length_value   = 0
            if not self.pulse2.enabled:   self.pulse2.length_value   = 0
            if not self.triangle.enabled: self.triangle.length_value = 0
            if not self.noise.enabled:    self.noise.length_value    = 0
        elif addr == 0x4017:
            self._frame_mode  = (data >> 7) & 1
            self._irq_inhibit = bool(data & 0x40)
            if self._irq_inhibit:
                self._frame_irq = False
            self._frame_counter = 0

    def cpu_read(self, addr: int) -> int:
        if addr == 0x4015:
            val = 0
            if self.pulse1.length_value   > 0: val |= 0x01
            if self.pulse2.length_value   > 0: val |= 0x02
            if self.triangle.length_value > 0: val |= 0x04
            if self.noise.length_value    > 0: val |= 0x08
            if self._frame_irq:               val |= 0x40
            self._frame_irq = False
            return val
        return 0

    # ─── Frame counter ───

    def _clock_frame_counter(self):
        """Cloca el frame counter (cuartos de frame)."""
        self._frame_counter += 1

        if self._frame_mode == 0:   # 4-step
            steps = (3728, 7456, 11185, 14914)
            if self._frame_counter in steps:
                quarter = self._frame_counter in (3728, 7456, 11185, 14914)
                half    = self._frame_counter in (7456, 14914)
                self._clock_envelopes(quarter)
                self._clock_lengths_sweeps(half)
            if self._frame_counter == 14914:
                if not self._irq_inhibit:
                    self._frame_irq  = True
                    self.irq_pending = True
                self._frame_counter = 0
        else:   # 5-step
            steps = (3728, 7456, 11185, 14914, 18640)
            if self._frame_counter in steps:
                quarter = True
                half    = self._frame_counter in (7456, 18640)
                self._clock_envelopes(quarter)
                self._clock_lengths_sweeps(half)
            if self._frame_counter == 18640:
                self._frame_counter = 0

    def _clock_envelopes(self, do_it: bool):
        if do_it:
            self.pulse1.envelope.clock()
            self.pulse2.envelope.clock()
            self.triangle.clock_linear()
            self.noise.envelope.clock()

    def _clock_lengths_sweeps(self, do_it: bool):
        if do_it:
            self.pulse1.clock_length()
            self.pulse1.clock_sweep()
            self.pulse2.clock_length()
            self.pulse2.clock_sweep()
            self.triangle.clock_length()
            self.noise.clock_length()

    # ─── Mezclador de audio ───

    def _mix(self) -> float:
        """
        Mezcla las salidas de todos los canales.
        Usa la fórmula de mezcla no-lineal del NES real.
        """
        p1 = self.pulse1.output
        p2 = self.pulse2.output
        t  = self.triangle.output
        n  = self.noise.output

        pulse_out = 0.0
        if p1 + p2 > 0:
            pulse_out = 95.88 / (8128.0 / (p1 + p2) + 100.0)

        tnd_out = 0.0
        tnd_sum = t / 8227.0 + n / 12241.0
        if tnd_sum > 0:
            tnd_out = 159.79 / (1.0 / tnd_sum + 100.0)

        return pulse_out + tnd_out

    # ─── Ciclo principal ───

    def clock(self):
        """Avanza la APU un ciclo de reloj (se llama cada ciclo de CPU)."""
        # Los canales pulse se clocan cada 2 ciclos
        if self._clock_count & 1:
            self.pulse1.clock_timer()
            self.pulse2.clock_timer()
            self.noise.clock_timer()
        # Triangle se cloca cada ciclo
        self.triangle.clock_timer()

        self._clock_frame_counter()

        # Downsampling: generar una muestra de audio
        self._sample_accum += self._mix()
        self._sample_count += 1

        # Cada X ciclos de CPU generamos una muestra de 44100 Hz
        cycles_per_sample = self.CPU_FREQ / self.SAMPLE_RATE
        if self._clock_count % int(cycles_per_sample) == 0:
            if self._sample_count > 0:
                sample = self._sample_accum / self._sample_count
                self._sample_buffer.append(sample)
                self._sample_accum = 0.0
                self._sample_count = 0

        self._clock_count += 1

    def get_samples(self) -> list[float]:
        """Devuelve y vacía el buffer de muestras."""
        buf = self._sample_buffer[:]
        self._sample_buffer.clear()
        return buf
