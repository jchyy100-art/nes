"""
controller.py — Control Xbox (Bluetooth / USB) para el NES
============================================================
Este módulo maneja el input del jugador usando pygame.joystick,
que funciona con cualquier control conectado por Bluetooth o USB
en Windows (Xbox One/Series, Xbox 360, etc.).

Mapa de botones Xbox → NES:
    A        (btn 0)  → A del NES
    B        (btn 1)  → B del NES
    X        (btn 2)  → Turbo A
    Y        (btn 3)  → Turbo B
    Start    (btn 7)  → Start del NES
    Back/View(btn 6)  → Select del NES
    LB       (btn 4)  → Guardar estado rápido
    RB       (btn 5)  → Cargar estado rápido
    D-Pad    (hat 0)  → Direcciones del NES

También soporta teclado como fallback (WASD o flechas).

Registro de botones del NES (1 byte, leído en serie):
    Bit 7: A
    Bit 6: B
    Bit 5: Select
    Bit 4: Start
    Bit 3: Up
    Bit 2: Down
    Bit 1: Left
    Bit 0: Right
try:
    import pygame
    PYGAME_AVAILABLE = True
except Exception:
    pygame = None
    PYGAME_AVAILABLE = False


class Controller:
    """
    Emula el controlador del NES.
    Soporta control Xbox por Bluetooth y teclado como fallback.
    """

    # ─── Constantes de botones del NES ───
    BTN_A      = 0x80
    BTN_B      = 0x40
    BTN_SELECT = 0x20
    BTN_START  = 0x10
    BTN_UP     = 0x08
    BTN_DOWN   = 0x04
    BTN_LEFT   = 0x02
    BTN_RIGHT  = 0x01

    # ─── Botones de Xbox (índices de pygame) ───
    XBOX_A      = 0
    XBOX_B      = 1
    XBOX_X      = 2
    XBOX_Y      = 3
    XBOX_LB     = 4
    XBOX_RB     = 5
    XBOX_BACK   = 6
    XBOX_START  = 7
    XBOX_LS     = 8
    XBOX_RS     = 9

    def __init__(self, player: int = 1):
        """
        player: 1 o 2 (para soporte de dos jugadores en el futuro)
        """
        self.player = player

        # Estado actual de los botones del NES (1 byte)
        self.state = 0x00

        # Registro de lectura serial (la CPU lee bit a bit)
        self._shift_reg = 0x00
        self._strobe    = False   # cuando True, siempre devuelve el estado de A

        # ─── Turbo ───
        self._turbo_a = False
        self._turbo_b = False
        self._turbo_tick = 0

        # ─── Joystick ───
        self.joystick = None
        self.manual_override = False
        self._init_joystick()

        # ─── Funciones extra (guardar/cargar estado) ───
        self.save_state_pressed  = False
        self.load_state_pressed  = False
        self.reset_pressed       = False
        self.pause_pressed       = False

    def set_button_mask(self, mask: int):
        """Asigna directamente el estado de los botones (usado por WebSocket/Web)."""
        self.manual_override = True
        self.state = mask & 0xFF

    def _init_joystick(self):
        """Detecta e inicializa el primer joystick disponible de forma segura."""
        if not PYGAME_AVAILABLE or not pygame:
            return
        try:
            if pygame.joystick.get_init() and pygame.joystick.get_count() > 0:
                idx = min(self.player - 1, pygame.joystick.get_count() - 1)
                self.joystick = pygame.joystick.Joystick(idx)
                self.joystick.init()
                name = self.joystick.get_name()
                print(f"[CTRL P{self.player}] Control detectado: {name}")
            else:
                print(f"[CTRL P{self.player}] Sin control fisico local.")
        except Exception:
            self.joystick = None

    def reconnect(self):
        """Intenta reconectar el control (útil si se desconectó)."""
        if not PYGAME_AVAILABLE or not pygame:
            return
        try:
            pygame.joystick.quit()
            pygame.joystick.init()
            self._init_joystick()
        except Exception:
            self.joystick = None

    # ═══════════════════════════════════════════════════════════════════════
    #                        ACTUALIZACIÓN DE ESTADO
    # ═══════════════════════════════════════════════════════════════════════

    def update(self, events: list = None):
        """
        Actualiza el estado del controlador.
        Debe llamarse una vez por frame, pasando los eventos de pygame.
        """
        # Si estamos recibiendo input por WebSocket / red, no sobreescribir con pygame local
        if self.manual_override:
            return

        # Resetear botones extra
        self.save_state_pressed = False
        self.load_state_pressed = False
        self.reset_pressed      = False
        self.pause_pressed      = False

        new_state = 0x00

        # ─── Joystick Xbox ───
        if self.joystick:
            new_state |= self._read_joystick()
        else:
            try:
                if pygame.joystick.get_init() and pygame.joystick.get_count() > 0:
                    self._init_joystick()
            except Exception:
                pass

        # ─── Teclado (siempre activo como fallback) ───
        new_state |= self._read_keyboard()

        # ─── Turbo ───
        self._turbo_tick = (self._turbo_tick + 1) % 4
        turbo_active = self._turbo_tick < 2   # alterna cada 2 frames

        if self._turbo_a and turbo_active:
            new_state |= self.BTN_A
        if self._turbo_b and turbo_active:
            new_state |= self.BTN_B

        self.state = new_state

    def _read_joystick(self) -> int:
        """Lee el estado del control Xbox."""
        state = 0x00
        joy   = self.joystick

        try:
            # ─── Botones principales ───
            if joy.get_button(self.XBOX_A):
                state |= self.BTN_A
            if joy.get_button(self.XBOX_B):
                state |= self.BTN_B
            if joy.get_button(self.XBOX_START):
                state |= self.BTN_START
            if joy.get_button(self.XBOX_BACK):
                state |= self.BTN_SELECT

            # ─── Turbo (X=turbo A, Y=turbo B) ───
            self._turbo_a = joy.get_button(self.XBOX_X)
            self._turbo_b = joy.get_button(self.XBOX_Y)

            # ─── Funciones extra ───
            if joy.get_button(self.XBOX_LB):
                self.save_state_pressed = True
            if joy.get_button(self.XBOX_RB):
                self.load_state_pressed = True

            # ─── D-Pad (hat) ───
            if joy.get_numhats() > 0:
                hx, hy = joy.get_hat(0)
                if hy > 0:  state |= self.BTN_UP
                if hy < 0:  state |= self.BTN_DOWN
                if hx < 0:  state |= self.BTN_LEFT
                if hx > 0:  state |= self.BTN_RIGHT

            # ─── Stick izquierdo como alternativa al D-Pad ───
            if joy.get_numaxes() >= 2:
                ax = joy.get_axis(0)   # horizontal
                ay = joy.get_axis(1)   # vertical
                dead_zone = 0.4
                if ay < -dead_zone: state |= self.BTN_UP
                if ay >  dead_zone: state |= self.BTN_DOWN
                if ax < -dead_zone: state |= self.BTN_LEFT
                if ax >  dead_zone: state |= self.BTN_RIGHT

        except Exception:
            # Si el control se desconecta durante el juego
            self.joystick = None

        return state

    def _read_keyboard(self) -> int:
        """Lee las teclas del teclado (fallback y debug)."""
        if not PYGAME_AVAILABLE or not pygame:
            return 0
        state  = 0x00
        try:
            keys = pygame.key.get_pressed()
        except Exception:
            return 0

        # Player 1: flechas + Z,X / Enter, Shift_R
        if self.player == 1:
            if keys[pygame.K_z]        or keys[pygame.K_KP1]:  state |= self.BTN_A
            if keys[pygame.K_x]        or keys[pygame.K_KP2]:  state |= self.BTN_B
            if keys[pygame.K_RETURN]   or keys[pygame.K_KP0]:  state |= self.BTN_START
            if keys[pygame.K_RSHIFT]   or keys[pygame.K_KP_ENTER]: state |= self.BTN_SELECT
            if keys[pygame.K_UP]    or keys[pygame.K_w]: state |= self.BTN_UP
            if keys[pygame.K_DOWN]  or keys[pygame.K_s]: state |= self.BTN_DOWN
            if keys[pygame.K_LEFT]  or keys[pygame.K_a]: state |= self.BTN_LEFT
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]: state |= self.BTN_RIGHT
        # Player 2: IJKL + Q,E
        else:
            if keys[pygame.K_q]: state |= self.BTN_A
            if keys[pygame.K_e]: state |= self.BTN_B
            if keys[pygame.K_p]: state |= self.BTN_START
            if keys[pygame.K_o]: state |= self.BTN_SELECT
            if keys[pygame.K_i]: state |= self.BTN_UP
            if keys[pygame.K_k]: state |= self.BTN_DOWN
            if keys[pygame.K_j]: state |= self.BTN_LEFT
            if keys[pygame.K_l]: state |= self.BTN_RIGHT

        # ─── Teclas de sistema (iguales para ambos jugadores) ───
        if keys[pygame.K_F5]: self.save_state_pressed = True
        if keys[pygame.K_F8]: self.load_state_pressed = True
        if keys[pygame.K_r]:  self.reset_pressed      = True
        if keys[pygame.K_p]:  self.pause_pressed      = True

        return state

    # ═══════════════════════════════════════════════════════════════════════
    #          COMUNICACIÓN CON LA CPU (lectura serial de botones)
    # ═══════════════════════════════════════════════════════════════════════

    def cpu_write(self, data: int):
        """
        La CPU escribe $4016 (jugador 1) o $4017 (jugador 2).
        Bit 0 = strobe. Cuando strobe=1, el shift register se recarga
        continuamente con el estado actual.
        """
        self._strobe = bool(data & 0x01)
        if self._strobe:
            self._shift_reg = self.state

    def cpu_read(self) -> int:
        """
        La CPU lee $4016 o $4017 para obtener un bit del estado.
        Devuelve el bit más significativo del shift register y lo desplaza.
        """
        if self._strobe:
            # Siempre devuelve el estado del botón A mientras strobe=1
            return 1 if (self.state & self.BTN_A) else 0

        data = 1 if (self._shift_reg & 0x80) else 0
        self._shift_reg = (self._shift_reg << 1) | 0x01   # rellenar con 1s
        return data | 0x40   # bits 6-7 siempre 1 en el NES original

    # ─── Info de depuración ───

    def debug_info(self) -> str:
        """Devuelve una cadena con el estado actual de los botones."""
        s = self.state
        pressed = []
        if s & self.BTN_A:      pressed.append("A")
        if s & self.BTN_B:      pressed.append("B")
        if s & self.BTN_SELECT: pressed.append("SEL")
        if s & self.BTN_START:  pressed.append("STA")
        if s & self.BTN_UP:     pressed.append("↑")
        if s & self.BTN_DOWN:   pressed.append("↓")
        if s & self.BTN_LEFT:   pressed.append("←")
        if s & self.BTN_RIGHT:  pressed.append("→")
        ctrl_name = self.joystick.get_name() if self.joystick else "Teclado"
        return f"[{ctrl_name}] P{self.player}: {' '.join(pressed) or '---'}"
