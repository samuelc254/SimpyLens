import tkinter as tk
import time
from tkinter import ttk, messagebox
import simpy
from .monkey_patch import recursos_rastreados, transferencias_pendentes, apply_patch
from .sim_manager import SimulationController
import math
import os
import sys


class SimPyVisualizer(tk.Tk):
    def __init__(self, setup_func=None, title="SimPy Visualizer"):
        """
        Initializes the SimPy Visualizer.

        :param setup_func: A function that takes a simpy.Environment as its only argument
                           and sets up the simulation (creats resources, processes, etc).
        :param title: Window title.
        """
        # Garante que o patch esteja aplicado
        apply_patch()
        super().__init__()
        self.title(title)
        self.geometry("1000x800")

        # Variáveis de Controle
        self.env = None
        self.running = False
        self.target_time = 100.0
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0

        # Módulo de simulação atual / Função de setup
        self.current_setup_func = setup_func

        # Controle de Animação
        self.obj_coords_cache = {}  # Cache para guardar (x, y) de cada objeto visual
        self.active_animations = []  # Lista de animações correndo
        self.active_list_widgets = {}  # Dict {id(rec): widget_frame} para reutilizar widgets e manter scroll

        # Variáveis para cálculo de FPS (Ticks/s)
        self.last_tick_time = time.time()
        self.tick_count = 0
        self.last_fps_update = 0

        # Setup UI
        self._setup_top_bar()
        self._setup_canvas()

        # Controller (separa lógica da simulação)
        self.sim_ctrl = SimulationController(
            draw_callback=lambda initial=False: (self.draw_scene(initial), self.update_idletasks()),
            start_animations_cb=self.start_animations,
            update_time_cb=self.update_time_display,
            schedule_cb=lambda ms, fn: self.after(ms, fn),
            speed_getter=lambda: self.scl_speed.get(),
            on_pause_cb=lambda: self.ent_target.config(state="normal"),
        )

        # Inicializa Simulação se tiver setup function
        if self.current_setup_func:
            try:
                self.sim_ctrl.reset(self.current_setup_func)
            except Exception as e:
                messagebox.showerror("Simulation Error", f"Error in setup():\n{e}")

    def update_time_display(self, now):
        """Atualiza o label de tempo e calcula ticks/s na interface."""
        self.lbl_time.config(text=f"Time: {now:.2f}")

        # Cálculo de Ticks/s (tps)
        # self.sim_ctrl chama isso a cada step ou frame

        current = time.time()

        # Incrementa contador de chamadas entre atualizações do display
        self.tick_count += 1

        # Atualiza o display a cada 0.5 segundos para não ficar piscando
        elapsed = current - self.last_fps_update
        if elapsed >= 0.5:
            # tps = steps / segundos
            if elapsed > 0:
                tps = self.tick_count / elapsed
                self.lbl_speed_val.config(text=f"{tps:.1f} tps")

            # Reset para próximo intervalo
            self.last_fps_update = current
            self.tick_count = 0

    def _setup_top_bar(self):
        # Frame principal da barra
        top_container = ttk.Frame(self)
        top_container.pack(side=tk.TOP, fill=tk.X)

        # Barra de Controles (Existente)
        bar = ttk.Frame(top_container, padding=5)
        bar.pack(side=tk.TOP, fill=tk.X)

        # Botões de Controle
        btn_frame = ttk.Frame(bar)
        btn_frame.pack(side=tk.LEFT, padx=5)

        ttk.Button(
            btn_frame,
            text="▶ Play",
            command=lambda: (
                self.ent_target.config(state="disabled"),
                self.sim_ctrl.set_setup_func(self.current_setup_func),
                setattr(
                    self.sim_ctrl,
                    "target_time",
                    float(self.ent_target.get().strip()) if self.ent_target.get().strip() else float("inf"),
                )
                or self.sim_ctrl.run(),
            ),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⏯ Step", command=lambda: (self.sim_ctrl.set_setup_func(self.current_setup_func), self.sim_ctrl.run_single_step())).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⏸ Pause", command=lambda: (self.sim_ctrl.pause(), self.ent_target.config(state="normal"))).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⏹ Reset", command=lambda: (self.sim_ctrl.reset(self.current_setup_func), self.ent_target.config(state="normal"), self.after(100, self.center_view))).pack(
            side=tk.LEFT, padx=2
        )

        # Display Time
        self.lbl_time = ttk.Label(bar, text="Time: 0.00", font=("Consolas", 14, "bold"))
        self.lbl_time.pack(side=tk.LEFT, padx=20)

        # Simulation Speed Control (Logarithmic Scale)
        spd_frame = ttk.Frame(bar)
        spd_frame.pack(side=tk.LEFT, padx=20)
        ttk.Label(spd_frame, text="Speed:").pack(side=tk.LEFT)
        # Slider 0 to 100 (abstract)
        # 0 = Slow (500ms), 100 = Fast (1ms)
        self.scl_speed = tk.Scale(spd_frame, from_=0, to=100, orient=tk.HORIZONTAL, showvalue=0, length=150)
        self.scl_speed.set(50)
        self.scl_speed.pack(side=tk.LEFT)

        # FPS / Ticks/s Label
        self.lbl_speed_val = ttk.Label(spd_frame, text="0.0 tps", width=12)
        self.lbl_speed_val.pack(side=tk.LEFT, padx=(5, 0))

        # Break Point Control
        right_frame = ttk.Frame(bar)
        right_frame.pack(side=tk.RIGHT, padx=5)

        ttk.Label(right_frame, text="Break Point:").pack(side=tk.LEFT, padx=(5, 5))
        self.ent_target = ttk.Entry(right_frame, width=10)
        self.ent_target.insert(0, "100")
        self.ent_target.pack(side=tk.LEFT)

    def update_time_display(self, now):
        """Atualiza o label de tempo e calcula ticks/s na interface."""
        self.lbl_time.config(text=f"Time: {now:.2f}")

        # Cálculo de Ticks/s (tps)
        # self.sim_ctrl chama isso a cada step ou frame

        current = time.time()

        # Incrementa contador de chamadas entre atualizações do display
        self.tick_count += 1

        # Atualiza o display a cada 0.5 segundos para não ficar piscando
        elapsed = current - self.last_fps_update
        if elapsed >= 0.5:
            # tps = steps / segundos
            if elapsed > 0:
                tps = self.tick_count / elapsed
                self.lbl_speed_val.config(text=f"{tps:.1f} tps")

            # Reset para próximo intervalo
            self.last_fps_update = current
            self.tick_count = 0

    def _setup_canvas(self):
        self.canvas_frame = tk.Frame(self)  # Container for canvas + floating buttons
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.canvas_frame, bg="#f0f0f0")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Center View Button (Floating bottom-right)
        self.btn_center = tk.Button(self.canvas, text="🎯 Center View", command=self.center_view, bg="white", relief="raised")
        # To place it floating, we use a window inside the canvas or pack/place relative to frame
        # Using place relative to the canvas widget is better for floating UI
        self.btn_center.place(relx=1.0, rely=1.0, anchor="se", x=-20, y=-20)

        # Binds
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_click)
        self.canvas.bind("<B1-Motion>", self.do_pan)
        self.canvas.bind("<ButtonRelease-1>", self.stop_pan)  # Necessário para restaurar estado se escondermos algo
        self.canvas.bind("<MouseWheel>", self.do_zoom)
        self.canvas.bind("<Button-4>", self.do_zoom)
        self.canvas.bind("<Button-5>", self.do_zoom)

    def on_canvas_click(self, event):
        # Transforma coordenadas de tela para coordenadas do canvas (considerando pan/zoom)
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        # Verifica clique nos botões de expandir
        clicked_items = self.canvas.find_overlapping(cx, cy, cx + 1, cy + 1)

        for item in clicked_items:
            tags = self.canvas.gettags(item)
            for tag in tags:
                if tag.startswith("btn_expand_"):
                    # Extrai o ID do objeto recurso
                    try:
                        obj_id = int(tag.split("_")[-1])

                        # Procura o objeto no conjunto rastreado pelo ID
                        target_rec = None
                        for r in recursos_rastreados:
                            if id(r) == obj_id:
                                target_rec = r
                                break

                        if target_rec:
                            # Toggle expand state
                            current_state = getattr(target_rec, "is_expanded", False)
                            target_rec.is_expanded = not current_state
                            self.draw_scene()

                    except (ValueError, IndexError):
                        pass
                    return

        # Se não clicou em botão, inicia o Pan
        self.start_pan(event)

    def start_pan(self, event):
        # Guarda a posição inicial do mouse para o Pan manual
        self.pan_start_x = event.x
        self.pan_start_y = event.y

    def stop_pan(self, event):
        # Restaura visibilidade e corrige posição final
        # Ao restaurar state, o canvas vai desenhar na nova posição correta
        pass

        # Opcional: draw_scene completo para garantir alinhamento perfeito de fontes
        # self.draw_scene()

    def do_pan(self, event):
        # Calcula o deslocamento
        dx = event.x - self.pan_start_x
        dy = event.y - self.pan_start_y

        # Define limite mínimo para mover (deadzone) para evitar tremedeira em cliques simples
        if abs(dx) < 2 and abs(dy) < 2:
            return

        # Move todos os objetos do canvas visualmente
        self.canvas.move("all", dx, dy)

        # Atualiza o offset global para persistir o movimento no próximo redesenho (draw_scene)
        self.offset_x += dx
        self.offset_y += dy

        # Atualiza a referência para o próximo movimento
        self.pan_start_x = event.x
        self.pan_start_y = event.y

    def do_zoom(self, event):
        # Zoom correto exige redesenho de widgets complexos (Listbox) que não escalam com canvas.scale
        # Calcula onde o mouse está no MUNDO (relativo ao conteúdo sem offset)
        # MundoX = (MouseX - OffsetX) / ZoomAntigo
        world_x = (event.x - self.offset_x) / self.scale
        world_y = (event.y - self.offset_y) / self.scale

        if event.delta > 0 or event.num == 4:
            factor = 1.1
        else:
            factor = 0.9

        new_scale = self.scale * factor
        # Limites de zoom
        if new_scale < 0.1 or new_scale > 5.0:
            return

        self.scale = new_scale

        # Recalcula Offset para manter o ponto do mouse fixo
        # NovoOffsetX = MouseX - (WorldX * NovoZoom)
        self.offset_x = event.x - (world_x * self.scale)
        self.offset_y = event.y - (world_y * self.scale)

        # Redesenha tudo com a nova escala e offsets
        self.draw_scene()

    def center_view(self):
        # 1. Reseta para escala 1.0 para calcular BBox 'original'
        self.canvas.delete("all")
        self.scale = 1.0
        self.draw_scene(initial=True)

        self.update_idletasks()  # Garante atualização de geometria

        bbox = self.canvas.bbox("all")
        if not bbox:
            return

        # 2. Dimensões do Conteúdo
        content_w = bbox[2] - bbox[0]
        content_h = bbox[3] - bbox[1]

        # 3. Dimensões da Janela (com margem de 50px)
        cw = self.canvas.winfo_width() - 100
        ch = self.canvas.winfo_height() - 100

        if cw <= 0 or ch <= 0:
            return  # Canvas muito pequeno ainda

        # 4. Calcula Escala Ideal (Fit)
        desired_scale = 1.0

        if content_w > 0 and content_h > 0:
            scale_w = cw / content_w
            scale_h = ch / content_h

            # Usa o menor fator para caber tudo (Fit Inside)
            desired_scale = min(scale_w, scale_h)
            desired_scale = min(desired_scale, 1.0)  # Não aumenta muito se for pequeno (max 1.0)
            desired_scale = max(desired_scale, 0.1)  # Não diminui demais

        self.scale = desired_scale

        # 5. Redesenha tudo com a nova escala (Resetando offsets temporariamente)
        self.offset_x = 0
        self.offset_y = 0
        self.canvas.delete("all")
        self.draw_scene(initial=True)

        # 6. Centraliza visualmente na tela
        self.update_idletasks()
        bbox_new = self.canvas.bbox("all")

        if bbox_new:
            nw_w = bbox_new[2] - bbox_new[0]
            nw_h = bbox_new[3] - bbox_new[1]

            # Centro da tela
            cx = self.canvas.winfo_width() / 2
            cy = self.canvas.winfo_height() / 2

            # Centro do conteúdo atual
            ccx = bbox_new[0] + nw_w / 2
            ccy = bbox_new[1] + nw_h / 2

            # Deslocamento
            dx = cx - ccx
            dy = cy - ccy

            self.canvas.move("all", dx, dy)

            # Atualiza offsets para persistir a centralização
            self.offset_x = dx
            self.offset_y = dy

        # Limpa transferências pendentes para evitar bolinhas voando na tela de reset
        if transferencias_pendentes:
            transferencias_pendentes.clear()

        self.active_animations = []
        self.obj_coords_cache = {}

    def reset_simulation(self):
        # Removed: simulation management moved to SimulationController
        pass

    def run_simulation(self):
        # Removed: moved to SimulationController
        pass

    def run_single_step(self):
        # Removed: moved to SimulationController
        pass

    def pause_simulation(self):
        # Removed: moved to SimulationController
        pass

    def step(self):
        # Removed: moved to SimulationController
        pass

    def start_animations(self, transfers, duration_ms):
        """Inicia uma animação suave de bolinhas voando entre recursos"""
        # Adapta taxa de atualização para duração
        target_step_time = 33  # ~30fps

        if duration_ms < target_step_time:
            step_time = max(1, duration_ms)
            frames = 1
        else:
            step_time = target_step_time
            frames = int(duration_ms / step_time)

        anim_objs = []
        for t in transfers:
            origin = t["from"]
            dest = t["to"]

            # Recupera coordenadas do cache (salvas em draw_scene / _draw_block_for_resource)
            p1 = self.obj_coords_cache.get(origin, (0, 0))
            p2 = self.obj_coords_cache.get(dest, (0, 0))

            # Se as coordenadas forem (0,0), o objeto talvez não esteja visível ou cache não foi populado corretamente
            if p1 == (0, 0) or p2 == (0, 0):
                continue

            # Cria a bolinha vermelha
            cx, cy = p1
            r = 5 * self.scale
            ball = self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#E74C3C", outline="black", width=1)

            anim_objs.append({"id": ball, "x1": p1[0], "y1": p1[1], "x2": p2[0], "y2": p2[1]})

        if anim_objs:
            self.animate_frame(anim_objs, frames, 0, step_time)

    def animate_frame(self, anim_objs, total_frames, current_frame, step_time):
        if current_frame >= total_frames:
            # Fim da animação, remove objetos
            for obj in anim_objs:
                self.canvas.delete(obj["id"])
            return

        # Progresso (0.0 a 1.0)
        t = (current_frame + 1) / total_frames

        r = 5 * self.scale
        for obj in anim_objs:
            # Interpolação Linear
            curr_x = obj["x1"] + (obj["x2"] - obj["x1"]) * t
            curr_y = obj["y1"] + (obj["y2"] - obj["y1"]) * t

            self.canvas.coords(obj["id"], curr_x - r, curr_y - r, curr_x + r, curr_y + r)

        # Agenda próximo frame
        self.after(step_time, self.animate_frame, anim_objs, total_frames, current_frame + 1, step_time)

    def draw_scene(self, initial=False):
        if not initial:
            # Ao deletar "all", os items create_window somem do canvas,
            # mas os Widgets Tkinter (Frames/Listboxes) associados continuam existindo na memória.
            # Precisamos gerenciá-los manualmente:
            # - Se o recurso ainda está expandido, queremos REUTILIZAR o widget (para manter scroll).
            # - Se o recurso foi fechado ou removeu, destruímos o widget.
            self.canvas.delete("all")

        # Identifica quais widgets estão ativos antes do desenho
        previously_active_ids = set(self.active_list_widgets.keys())
        currently_active_ids = set()

        now = 0.0
        if hasattr(self, "sim_ctrl") and self.sim_ctrl.env is not None:
            now = self.sim_ctrl.env.now
        self.lbl_time.config(text=f"Time: {now:.2f}")

        # Posição inicial considerando o PAN acumulado
        start_x = (50 * self.scale) + self.offset_x
        start_y = (50 * self.scale) + self.offset_y

        # Dimensões do Bloco + Margem
        block_w = 300 * self.scale
        block_h = 100 * self.scale
        margin = 20 * self.scale

        # Snapshot para evitar modificação durante iteração e para ter ordem estável se possível
        # Convertemos WeakSet para lista
        lista_recursos = list(recursos_rastreados)
        # Ordenamos por nome para estabilidade visual, se possível, ou ID
        # Como 'nome_visual' é adicionado pelo patch, podemos usar.
        lista_recursos.sort(key=lambda r: getattr(r, "nome_visual", str(id(r))))

        total = len(lista_recursos)

        # Se não há recursos, não desenha nada
        if total == 0:
            return

        # Estrutura para calcular posições
        # col_heights[c] = y_atual
        col_y_offsets = {}

        # Definindo número de colunas/linhas lógico
        if total <= 36:
            mode = "SQUARE"
            grid_dim = math.ceil(math.sqrt(total)) or 1
        else:
            mode = "RECT"
            fixed_rows = 6

        # Calcular onde cada item vai ficar
        for i, rec in enumerate(lista_recursos):
            # 1. Determina Coluna e Linha Lógicas
            if mode == "SQUARE":
                row_logical = i // grid_dim
                col_logical = i % grid_dim
            else:
                # Mode RECT (Cresce p/ direita, preenche de cima pra baixo)
                row_logical = i % fixed_rows
                col_logical = i // fixed_rows

            # 2. Calcula Altura do Item Atual
            base_h_scaled = 100 * self.scale
            h_atual = base_h_scaled

            if getattr(rec, "is_expanded", False):
                # Altura = 2 blocos + margem
                h_atual = (base_h_scaled * 2) + margin

            # 3. Calcula Posição X (Baseada na coluna lógica)
            # Largura da coluna é fixa baseada no bloco mais largo (que é padrão)
            col_width = (300 * self.scale) + margin
            x = start_x + (col_logical * col_width)

            # 4. Calcula Posição Y
            if col_logical not in col_y_offsets:
                col_y_offsets[col_logical] = start_y

            y = col_y_offsets[col_logical]

            # Desenha
            # Precisa passar índice na lista gerada agora, pois o índice do enumerate corresponde a ela
            # Passamos também currently_active_ids para rastrear widgets usados
            self._draw_block_for_resource(rec, x, y, i, lista_recursos, currently_active_ids)

            # Atualiza Y da próxima linha nessa coluna
            col_y_offsets[col_logical] += h_atual + margin

        # Limpa widgets que não foram usados neste frame (ex: usuário fechou o recurso)
        for rid in previously_active_ids:
            if rid not in currently_active_ids:
                # O widget não foi incluído no desenho, então ele não é mais visível
                # Destrói o Tk Frame
                widget = self.active_list_widgets.get(rid)
                if widget:
                    widget.destroy()
                del self.active_list_widgets[rid]

    def _draw_block_for_resource(self, rec, x, y, index, current_list, currently_active_ids):
        # index: índice na lista 'current_list' usada no draw_scene
        # currently_active_ids: set para registrar widgets usados neste frame

        # Altura base (colapsado)
        base_h = 100 * self.scale
        # Altura real (pode ser expandido)
        current_h = base_h
        expanded = getattr(rec, "is_expanded", False)

        if expanded:
            current_h = (base_h * 2) + (20 * self.scale)  # 2 blocos + gap

        w = 300 * self.scale
        h = current_h

        # --- CACHE DE COORDENADAS (CENTRO) PARA ANIMAÇÃO ---
        center_x = x + w / 2
        center_y = y + h / 2
        self.obj_coords_cache[rec] = (center_x, center_y)

        ocupados = 0
        cap = rec.capacity
        cor = "#ddd"
        tipo = "GENERICO"
        put_q = 0
        get_q = 0
        has_dual_queue = False
        items = []

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
            items = rec.items

        # --- Desenho do Bloco Principal ---
        self.canvas.create_rectangle(x, y, x + w, y + h, fill=cor, outline="black", width=2)

        # --- Botão Expandir (Store apenas) ---
        if isinstance(rec, simpy.Store):
            btn_sz = 20 * self.scale
            bx = x + w - btn_sz - 5 * self.scale
            by = y + 5 * self.scale
            symbol = "▲" if expanded else "▼"

            # Fundo Botão
            # Tag 'btn_expand_ID' identifica qual recurso expandir baseando-se no id do objeto
            btn_tag = f"btn_expand_{id(rec)}"
            self.canvas.create_rectangle(bx, by, bx + btn_sz, by + btn_sz, fill="white", outline="black", tags=(btn_tag,))
            self.canvas.create_text(bx + btn_sz / 2, by + btn_sz / 2, text=symbol, font=("Segoe UI", int(10 * self.scale)), tags=(btn_tag,))

        # Conteúdo (Títulos)
        font_title = ("Segoe UI", int(12 * self.scale), "bold")
        font_sub = ("Segoe UI", int(9 * self.scale), "italic")

        # Nome visual garantido pelo patch
        nome = getattr(rec, "nome_visual", "Resource")
        self.canvas.create_text(x + 10 * self.scale, y + 20 * self.scale, text=nome, anchor="w", font=font_title)
        self.canvas.create_text(x + 10 * self.scale, y + 40 * self.scale, text=f"{tipo} (Cap: {cap})", anchor="w", font=font_sub)

        # Barra
        bar_x = x + 10 * self.scale
        bar_y = y + 60 * self.scale
        bar_w = w - 20 * self.scale
        # Se expandido, a barra fica no topo ainda, o espaço extra é em baixo
        bar_h = 25 * self.scale

        self.canvas.create_rectangle(bar_x, bar_y, bar_x + bar_w, bar_y + bar_h, fill="white", outline="black")

        if cap > 0:
            pct = min(1.0, ocupados / cap)
            fill_w = bar_w * pct
            fill_color = "#27AE60" if pct < 1.0 else "#E67E22"
            self.canvas.create_rectangle(bar_x, bar_y, bar_x + fill_w, bar_y + bar_h, fill=fill_color, outline="")

        font_bar = ("Segoe UI", int(10 * self.scale), "bold")
        self.canvas.create_text(bar_x + bar_w / 2, bar_y + bar_h / 2, text=f"{ocupados}/{cap}", font=font_bar)

        # --- Conteudo Expandido (Lista de Itens) ---
        if expanded:
            rec_id = id(rec)
            list_y = y + 100 * self.scale  # Começa onde terminaria o bloco normal
            list_w = w - 20 * self.scale
            list_h = h - (110 * self.scale)

            # Reutiliza Widget ou Cria Novo
            if rec_id in self.active_list_widgets:
                # Reutilizar
                frame_container = self.active_list_widgets[rec_id]
                try:
                    # Tenta recuperar listbox. A ordem children é: barH, Box, barV (depende do pack).
                    # Mas podemos usar winfo_children() e filtrar por Type se necessário.
                    # Pelo código abaixo de criação: sb_v, sb_h, lbox são packed.
                    # A ordem em winfo_children segue a criação: sb_v(0), sb_h(1), lbox(2)
                    lbox = frame_container.winfo_children()[2]
                except IndexError:
                    # Fallback
                    lbox = None
            else:
                lbox = None
                frame_container = None

            # Calcula Lbox Font
            lbox_font = ("Consolas", int(9 * self.scale)) if self.scale > 0.5 else ("Consolas", 8)

            if frame_container is None or lbox is None:
                # Criar Novo
                frame_container = tk.Frame(self.canvas, bg="white", bd=1, relief="solid")
                sb_v = tk.Scrollbar(frame_container, orient=tk.VERTICAL)
                sb_h = tk.Scrollbar(frame_container, orient=tk.HORIZONTAL)

                lbox = tk.Listbox(frame_container, yscrollcommand=sb_v.set, xscrollcommand=sb_h.set, font=lbox_font, bg="#f9f9f9", bd=0, highlightthickness=0)
                sb_v.config(command=lbox.yview)
                sb_h.config(command=lbox.xview)
                sb_v.pack(side=tk.RIGHT, fill=tk.Y)
                sb_h.pack(side=tk.BOTTOM, fill=tk.X)
                lbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

                self.active_list_widgets[rec_id] = frame_container
            else:
                # Atualiza fonte e tamanho se já existir
                lbox.config(font=lbox_font)

            # Atualiza Conteúdo da Listbox sem perder posição do scroll
            # Pega lista de itens atuais
            current_items_str = [str(item) for item in items] if items else ["(Vazio)"]

            # Pega lista no widget
            # Listbox.get(0, END) retorna tupla de strings
            displayed_items = lbox.get(0, tk.END)

            # Se diferente, atualiza.
            if displayed_items != tuple(current_items_str):
                # Guarda posição do scroll atual (fração 0.0 a 1.0)
                y_scroll_pos = lbox.yview()
                x_scroll_pos = lbox.xview()

                # Simples: deleta tudo e insere novo conjunto
                lbox.delete(0, tk.END)
                for s in current_items_str:
                    lbox.insert(tk.END, s)

                if not items:
                    lbox.config(fg="#888")
                else:
                    lbox.config(fg="black")

                # Restaura scroll
                try:
                    lbox.yview_moveto(y_scroll_pos[0])
                    lbox.xview_moveto(x_scroll_pos[0])
                except:
                    pass

            # Adiciona ao Canvas (create_window)
            # Como deletamos "all" no começo, precisamos recriar o item do canvas apontando para o widget existente
            win_item = self.canvas.create_window(x + 10 * self.scale, list_y, width=list_w, height=list_h, anchor="nw", window=frame_container, tags=("window_widget",))

            # Marca como ativo neste frame
            currently_active_ids.add(rec_id)

        # Filas (Indicadores)
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
                cx, cy = x + w - 30 * self.scale, y + 20 * self.scale
                self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#E67E22", outline="white", width=2)
                self.canvas.create_text(cx, cy, text=str(get_q), fill="white", font=badge_font)
                self.canvas.create_text(cx, cy + r + 7 * self.scale, text="Q", font=label_font)
