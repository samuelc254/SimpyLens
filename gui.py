# gui.py
import tkinter as tk
from tkinter import ttk
import simpy
from monkey_patch import recursos_rastreados
import simu
import math


class SimPyVisualizer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SimPy Visualizer")
        self.geometry("1000x800")

        # Variáveis de Controle
        self.env = None
        self.running = False
        self.target_time = 100.0
        self.scale = 1.0

        # Setup UI
        self._setup_top_bar()
        self._setup_canvas()

        # Inicializa Simulação
        self.reset_simulation()

    def _setup_top_bar(self):
        bar = ttk.Frame(self, padding=5)
        bar.pack(side=tk.TOP, fill=tk.X)

        # Botões de Controle
        btn_frame = ttk.Frame(bar)
        btn_frame.pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_frame, text="▶ Play", command=self.run_simulation).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⏯ Step", command=self.run_single_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⏸ Pause", command=self.pause_simulation).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⏹ Reset", command=self.reset_simulation).pack(side=tk.LEFT, padx=2)

        # Display Tempo
        self.lbl_time = ttk.Label(bar, text="Tempo: 0.00", font=("Consolas", 14, "bold"))
        self.lbl_time.pack(side=tk.LEFT, padx=20)

        # Controle de Velocidade Simulação (Escala Logarítmica)
        spd_frame = ttk.Frame(bar)
        spd_frame.pack(side=tk.LEFT, padx=20)
        ttk.Label(spd_frame, text="Velocidade:").pack(side=tk.LEFT)
        # Slider de 0 a 100 (abstrato)
        # 0 = Lento (500ms), 100 = Rápido (1ms)
        self.scl_speed = tk.Scale(spd_frame, from_=0, to=100, orient=tk.HORIZONTAL, showvalue=0, length=150)
        self.scl_speed.set(50)
        self.scl_speed.pack(side=tk.LEFT)

        # Controle Tempo Alvo
        right_frame = ttk.Frame(bar)
        right_frame.pack(side=tk.RIGHT, padx=5)

        ttk.Label(right_frame, text="Alvo:").pack(side=tk.LEFT, padx=(5, 5))
        self.ent_target = ttk.Entry(right_frame, width=10)
        self.ent_target.insert(0, "100")
        self.ent_target.pack(side=tk.LEFT)

    def _setup_canvas(self):
        self.canvas = tk.Canvas(self, bg="#f0f0f0")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Binds
        self.canvas.bind("<ButtonPress-1>", self.start_pan)
        self.canvas.bind("<B1-Motion>", self.do_pan)
        self.canvas.bind("<MouseWheel>", self.do_zoom)
        self.canvas.bind("<Button-4>", self.do_zoom)
        self.canvas.bind("<Button-5>", self.do_zoom)

    def start_pan(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def do_pan(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def do_zoom(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)

        if event.delta > 0 or event.num == 4:
            factor = 1.1
        else:
            factor = 0.9

        new_scale = self.scale * factor
        if new_scale < 0.2 or new_scale > 5.0:
            return

        self.scale = new_scale
        self.canvas.scale("all", x, y, factor, factor)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def reset_simulation(self):
        self.running = False
        recursos_rastreados.clear()

        # Reinicia ambiente SimPy e Setup do usuário
        self.env = simpy.Environment()
        simu.setup(self.env)

        self.ent_target.config(state="normal")

        self.canvas.delete("all")
        self.draw_scene(initial=True)

    def run_simulation(self):
        if not self.running:
            self.running = True
            self.ent_target.config(state="disabled")
            try:
                self.target_time = float(self.ent_target.get())
            except ValueError:
                self.target_time = 1000.0
            self.step()

    def run_single_step(self):
        self.running = False
        self.ent_target.config(state="normal")
        try:
            if self.env.peek() != simpy.core.Infinity:
                self.env.step()
                self.draw_scene()
        except simpy.core.EmptySchedule:
            pass

    def pause_simulation(self):
        self.running = False
        self.ent_target.config(state="normal")

    def step(self):
        if not self.running:
            self.ent_target.config(state="normal")
            return

        if self.env.peek() == simpy.core.Infinity or self.env.now >= self.target_time:
            self.running = False
            self.ent_target.config(state="normal")
            return

        try:
            self.env.step()
        except simpy.core.EmptySchedule:
            self.running = False
            self.ent_target.config(state="normal")
            return

        self.draw_scene()

        # Pega o valor do slider (0 a 100)
        val = self.scl_speed.get()

        # Converte para Delay em ms usando escala LOGARÍTMICA
        # 0 -> 500ms (Lento)
        # 100 -> 1ms (Rápido)
        # Fórmula: Delay = 500 * (1/500)^(val/100)
        # Isso garante precisão fina em velocidades altas (baixa latência)
        # e saltos maiores em baixas velocidades.
        delay_ms = int(500 * (0.002 ** (val / 100.0)))

        # Garante mínimo de 1ms
        delay_ms = max(1, delay_ms)

        self.after(delay_ms, self.step)

    def draw_scene(self, initial=False):
        if not initial:
            self.canvas.delete("all")

        self.lbl_time.config(text=f"Tempo: {self.env.now:.2f}")

        start_x = 50 * self.scale
        start_y = 50 * self.scale
        gap_y = 150 * self.scale

        for i, rec in enumerate(recursos_rastreados):
            x = start_x
            y = start_y + (i * gap_y)
            self._draw_block_for_resource(rec, x, y)

    def _draw_block_for_resource(self, rec, x, y):
        w = 300 * self.scale
        h = 100 * self.scale

        ocupados = 0
        cap = rec.capacity
        cor = "#ddd"
        tipo = "GENERICO"
        put_q = 0
        get_q = 0
        has_dual_queue = False

        if isinstance(rec, simpy.Resource):
            cor = "#AED6F1"
            tipo = "RESOURCE"
            ocupados = rec.count
            get_q = len(rec.queue)
        elif isinstance(rec, simpy.Container):
            cor = "#F9E79F"
            tipo = "CONTAINER"
            ocupados = rec.level
            put_q = len(rec.put_queue)
            get_q = len(rec.get_queue)
            has_dual_queue = True
        elif isinstance(rec, simpy.Store):
            cor = "#D2B4DE"
            tipo = "STORE"
            ocupados = len(rec.items)
            put_q = len(rec.put_queue)
            get_q = len(rec.get_queue)
            has_dual_queue = True

        # Desenho
        self.canvas.create_rectangle(x, y, x + w, y + h, fill=cor, outline="black", width=2)

        font_title = ("Segoe UI", int(12 * self.scale), "bold")
        font_sub = ("Segoe UI", int(9 * self.scale), "italic")

        self.canvas.create_text(x + 10 * self.scale, y + 20 * self.scale, text=rec.nome_visual, anchor="w", font=font_title)
        self.canvas.create_text(x + 10 * self.scale, y + 40 * self.scale, text=f"{tipo} (Cap: {cap})", anchor="w", font=font_sub)

        # Barra
        bar_x = x + 10 * self.scale
        bar_y = y + 60 * self.scale
        bar_w = w - 20 * self.scale
        bar_h = 25 * self.scale

        self.canvas.create_rectangle(bar_x, bar_y, bar_x + bar_w, bar_y + bar_h, fill="white", outline="black")

        if cap > 0:
            pct = min(1.0, ocupados / cap)
            fill_w = bar_w * pct
            fill_color = "#27AE60" if pct < 1.0 else "#E67E22"
            self.canvas.create_rectangle(bar_x, bar_y, bar_x + fill_w, bar_y + bar_h, fill=fill_color, outline="")

        font_bar = ("Segoe UI", int(10 * self.scale), "bold")
        self.canvas.create_text(bar_x + bar_w / 2, bar_y + bar_h / 2, text=f"{ocupados}/{cap}", font=font_bar)

        # Filas
        r = 15 * self.scale
        badge_font = ("Segoe UI", int(10 * self.scale), "bold")
        label_font = ("Segoe UI", int(7 * self.scale))

        if has_dual_queue:
            if put_q > 0:
                cx, cy = x + w - 30 * self.scale, y + 20 * self.scale
                self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#E67E22", outline="white", width=2)
                self.canvas.create_text(cx, cy, text=str(put_q), fill="white", font=badge_font)
                self.canvas.create_text(cx, cy + r + 7 * self.scale, text="PUT", font=label_font)
            if get_q > 0:
                cx, cy = x + w - 70 * self.scale, y + 20 * self.scale
                self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#C0392B", outline="white", width=2)
                self.canvas.create_text(cx, cy, text=str(get_q), fill="white", font=badge_font)
                self.canvas.create_text(cx, cy + r + 7 * self.scale, text="GET", font=label_font)
        else:
            if get_q > 0:
                cx = x + w - 30 * self.scale
                cy = y + 25 * self.scale
                self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#C0392B", outline="white", width=2)
                self.canvas.create_text(cx, cy, text=str(get_q), fill="white", font=badge_font)
                self.canvas.create_text(cx, cy + r + 8 * self.scale, text="FILA", font=label_font)
