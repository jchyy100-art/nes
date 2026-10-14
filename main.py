"""
main.py — Punto de entrada del emulador NES
============================================
Inicializa todos los componentes, carga la ROM y
ejecuta el game loop principal con pygame.

Uso:
    python main.py <ruta_a_rom.nes>
    python main.py donkey_kong.nes

Controles (teclado):
    Z / Numpad1  → A
    X / Numpad2  → B
    Enter        → Start
    Shift Der.   → Select
    Flechas / WASD → D-Pad
    F5           → Guardar estado
    F8           → Cargar estado
    R            → Reset
    ESC          → Salir

Controles (Xbox Bluetooth):
    A  → A del NES
    B  → B del NES
    X  → Turbo A
    Y  → Turbo B
    Start → Start
    Back  → Select
    D-Pad → Direcciones
    LB    → Guardar estado
    RB    → Cargar estado
"""

import sys
import os
import time
import pickle
import pygame
import numpy as np

# ─── Importar componentes del emulador ───────────────────────────────────────
from memory     import Bus
from cpu        import CPU
from ppu        import PPU
from apu        import APU
from cartridge  import Cartridge
from controller import Controller


# ─── Constantes de pantalla ──────────────────────────────────────────────────
NES_W         = 256
NES_H         = 240
SCALE         = 3          # Factor de escala (256×240 → 768×720)
WINDOW_W      = NES_W * SCALE
WINDOW_H      = NES_H * SCALE + 24   # +24 para barra de info
FPS_TARGET    = 60
AUDIO_RATE    = 44100
AUDIO_CHUNK   = 512


def build_system(rom_path: str):
    """
    Construye e interconecta todos los componentes del NES.
    Devuelve el bus del sistema listo para ejecutar.
    """
    bus  = Bus()
    cart = Cartridge(rom_path)
    bus.cart = cart

    ppu  = PPU(bus)
    bus.ppu = ppu

    apu  = APU(bus)
    bus.apu = apu

    cpu  = CPU(bus)
    bus.cpu = cpu

    ctrl1 = Controller(player=1)
    ctrl2 = Controller(player=2)
    bus.ctrl1 = ctrl1
    bus.ctrl2 = ctrl2

    bus.reset()
    return bus


def save_state(bus: Bus, slot: int = 0):
    """Guarda el estado completo del emulador en un archivo."""
    rom_name = os.path.splitext(
        os.path.basename(bus.cart.path))[0]
    path = f"{rom_name}_state{slot}.pkl"
    try:
        state = {
            'cpu_A':   bus.cpu.A,
            'cpu_X':   bus.cpu.X,
            'cpu_Y':   bus.cpu.Y,
            'cpu_SP':  bus.cpu.SP,
            'cpu_PC':  bus.cpu.PC,
            'cpu_P':   bus.cpu.P,
            'cpu_cyc': bus.cpu.total_cycles,
            'ram':     bytes(bus.ram),
            'ppu_vram': [bytes(nt) for nt in bus.ppu.name_table],
            'ppu_pal':  bytes(bus.ppu.palette),
            'ppu_oam':  bytes(bus.ppu.oam),
            'ppu_v':    bus.ppu._v,
            'ppu_t':    bus.ppu._t,
            'ppu_x':    bus.ppu._x,
            'ppu_w':    bus.ppu._w,
            'ppu_ctrl': bus.ppu._ctrl,
            'ppu_mask': bus.ppu._mask,
            'prg_ram':  bytes(bus.cart.prg_ram),
            'chr_ram':  bytes(bus.cart.chr_ram) if bus.cart.chr_ram else b'',
        }
        with open(path, 'wb') as f:
            pickle.dump(state, f)
        print(f"[SAVE] Estado guardado: {path}")
        return True
    except Exception as e:
        print(f"[SAVE] Error: {e}")
        return False


def load_state(bus: Bus, slot: int = 0):
    """Carga el estado del emulador desde un archivo."""
    rom_name = os.path.splitext(
        os.path.basename(bus.cart.path))[0]
    path = f"{rom_name}_state{slot}.pkl"
    if not os.path.exists(path):
        print(f"[LOAD] No existe el archivo: {path}")
        return False
    try:
        with open(path, 'rb') as f:
            state = pickle.load(f)

        bus.cpu.A          = state['cpu_A']
        bus.cpu.X          = state['cpu_X']
        bus.cpu.Y          = state['cpu_Y']
        bus.cpu.SP         = state['cpu_SP']
        bus.cpu.PC         = state['cpu_PC']
        bus.cpu.P          = state['cpu_P']
        bus.cpu.total_cycles = state['cpu_cyc']
        bus.ram[:]         = state['ram']

        for i, nt in enumerate(state['ppu_vram']):
            bus.ppu.name_table[i][:] = nt
        bus.ppu.palette[:] = state['ppu_pal']
        bus.ppu.oam[:]     = state['ppu_oam']
        bus.ppu._v         = state['ppu_v']
        bus.ppu._t         = state['ppu_t']
        bus.ppu._x         = state['ppu_x']
        bus.ppu._w         = state['ppu_w']
        bus.ppu._ctrl      = state['ppu_ctrl']
        bus.ppu._mask      = state['ppu_mask']
        bus.cart.prg_ram[:] = state['prg_ram']
        if bus.cart.chr_ram and state['chr_ram']:
            bus.cart.chr_ram[:] = state['chr_ram']

        print(f"[LOAD] Estado cargado: {path}")
        return True
    except Exception as e:
        print(f"[LOAD] Error: {e}")
        return False


def init_audio() -> pygame.mixer.Sound | None:
    """Inicializa el sistema de audio de pygame."""
    try:
        pygame.mixer.pre_init(
            frequency=AUDIO_RATE,
            size=-16,
            channels=1,
            buffer=AUDIO_CHUNK
        )
        pygame.mixer.init()
        print(f"[AUDIO] Audio iniciado: {AUDIO_RATE} Hz")
        return True
    except Exception as e:
        print(f"[AUDIO] No se pudo iniciar el audio: {e}")
        return False


def push_audio(bus: Bus, audio_ok: bool):
    """Envía las muestras de audio generadas por la APU a pygame."""
    if not audio_ok:
        return
    samples = bus.apu.get_samples()
    if not samples:
        return
    try:
        arr = np.array(samples, dtype=np.float32)
        arr = np.clip(arr, -1.0, 1.0)
        arr_int16 = (arr * 32767).astype(np.int16)
        sound = pygame.sndarray.make_sound(arr_int16)
        sound.play()
    except Exception:
        pass


def main():
    # ─── Argumentos ───
    if len(sys.argv) < 2:
        print("╔══════════════════════════════════════════════╗")
        print("║        Emulador NES en Python                ║")
        print("╠══════════════════════════════════════════════╣")
        print("║  Uso: python main.py <archivo.nes>           ║")
        print("║                                              ║")
        print("║  Controles Xbox:    Controles Teclado:       ║")
        print("║   A  → A del NES    Z / Numpad1              ║")
        print("║   B  → B del NES    X / Numpad2              ║")
        print("║   X  → Turbo A      (turbo no disponible)    ║")
        print("║   Y  → Turbo B                               ║")
        print("║   Start → Start     Enter                    ║")
        print("║   Back  → Select    Shift Der.               ║")
        print("║   D-Pad → Dirs      Flechas / WASD           ║")
        print("║   LB → Guardar      F5                       ║")
        print("║   RB → Cargar       F8                       ║")
        print("╚══════════════════════════════════════════════╝")
        sys.exit(0)

    rom_path = sys.argv[1]

    # ─── Inicializar pygame ───
    pygame.init()
    pygame.joystick.init()

    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("NES Emulator — Python")

    clock  = pygame.time.Clock()
    font   = pygame.font.SysFont("Consolas", 12)

    # ─── Inicializar audio ───
    audio_ok = init_audio()

    # ─── Cargar ROM y construir sistema ───
    print(f"\n[NES] Iniciando emulador...")
    try:
        bus = build_system(rom_path)
    except Exception as e:
        print(f"[ERROR] {e}")
        pygame.quit()
        sys.exit(1)

    # ─── Surface de la pantalla NES (256×240) ───
    nes_surface = pygame.Surface((NES_W, NES_H))

    # ─── Variables de estado ───
    running       = True
    paused        = False
    show_debug    = False
    frame_count   = 0
    fps_display   = 0.0
    fps_timer     = time.time()
    save_slot     = 0

    # ─── Notificaciones en pantalla ───
    notification      = ""
    notification_timer = 0

    print("[NES] Emulación iniciada. ESC para salir.\n")

    # ════════════════════════════════════════════════════════════
    #                        GAME LOOP
    # ════════════════════════════════════════════════════════════
    while running:
        # ─── Procesar eventos ───
        events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_F1:
                    show_debug = not show_debug
                elif event.key == pygame.K_PLUS or event.key == pygame.K_EQUALS:
                    save_slot = min(save_slot + 1, 9)
                elif event.key == pygame.K_MINUS:
                    save_slot = max(save_slot - 1, 0)

            # ─── Reconexión de control ───
            elif event.type == pygame.JOYDEVICEADDED:
                print(f"[CTRL] Control conectado (id={event.device_index})")
                bus.ctrl1.reconnect()
            elif event.type == pygame.JOYDEVICEREMOVED:
                print(f"[CTRL] Control desconectado")

        # ─── Actualizar controles ───
        bus.ctrl1.update(events)
        bus.ctrl2.update(events)

        # ─── Acciones especiales ───
        if bus.ctrl1.save_state_pressed:
            if save_state(bus, save_slot):
                notification       = f"✓ Estado guardado (slot {save_slot})"
                notification_timer = 180
        if bus.ctrl1.load_state_pressed:
            if load_state(bus, save_slot):
                notification       = f"✓ Estado cargado (slot {save_slot})"
                notification_timer = 180
        if bus.ctrl1.reset_pressed:
            bus.reset()
            notification       = "Sistema reseteado"
            notification_timer = 120
        if bus.ctrl1.pause_pressed:
            paused = not paused
            notification       = "PAUSA" if paused else "REANUDADO"
            notification_timer = 90

        # ─── Ejecutar ciclos hasta completar un frame ───
        if not paused:
            bus.ppu.frame_ready = False
            while not bus.ppu.frame_ready:
                bus.clock()

        # ─── Renderizar frame ───
        # Convertir el framebuffer numpy → pygame Surface
        pygame.surfarray.blit_array(
            nes_surface,
            bus.ppu.framebuffer.transpose(1, 0, 2)  # pygame usa (w,h,3)
        )

        # Escalar la imagen del NES al tamaño de la ventana
        scaled = pygame.transform.scale(
            nes_surface, (WINDOW_W, NES_H * SCALE))
        screen.blit(scaled, (0, 0))

        # ─── Barra de información ───
        bar_y = NES_H * SCALE
        pygame.draw.rect(screen, (20, 20, 20),
                         (0, bar_y, WINDOW_W, 24))

        ctrl_info = bus.ctrl1.debug_info()
        slot_info = f"Slot:{save_slot}"
        fps_info  = f"FPS:{fps_display:.0f}"
        info_txt  = f"  {fps_info}  {slot_info}  {ctrl_info}"
        info_surf = font.render(info_txt, True, (180, 180, 180))
        screen.blit(info_surf, (4, bar_y + 4))

        # ─── Notificaciones ───
        if notification_timer > 0:
            notif_surf = font.render(notification, True, (255, 220, 0))
            screen.blit(notif_surf, (WINDOW_W - notif_surf.get_width() - 8, bar_y + 4))
            notification_timer -= 1

        # ─── Debug info (F1) ───
        if show_debug:
            cpu = bus.cpu
            debug_lines = [
                f"PC:{cpu.PC:04X}  A:{cpu.A:02X}  X:{cpu.X:02X}  Y:{cpu.Y:02X}",
                f"SP:{cpu.SP:02X}  P:{cpu.P:08b}  Cyc:{cpu.total_cycles}",
                f"SL:{bus.ppu.scanline}  CYC:{bus.ppu.cycle}  FR:{bus.ppu.frame}",
            ]
            for i, line in enumerate(debug_lines):
                surf = font.render(line, True, (0, 255, 0))
                screen.blit(surf, (4, 4 + i * 14))

        pygame.display.flip()

        # ─── Audio ───
        push_audio(bus, audio_ok)

        # ─── FPS ───
        clock.tick(FPS_TARGET)
        frame_count += 1
        now = time.time()
        if now - fps_timer >= 1.0:
            fps_display = frame_count / (now - fps_timer)
            frame_count = 0
            fps_timer   = now
            pygame.display.set_caption(
                f"NES — {os.path.basename(rom_path)} — {fps_display:.1f} FPS")

    # ─── Salida limpia ───
    pygame.mixer.quit()
    pygame.quit()
    print("[NES] Emulador cerrado.")
    sys.exit(0)


if __name__ == "__main__":
    main()
