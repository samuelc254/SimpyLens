# gui.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import simpy
from monkey_patch import recursos_rastreados, transferencias_pendentes
import math
import importlib.util
import os
import sys

# Default simulation module (can be None)
default_simu = None
try:
    import simu

    default_simu = simu
except ImportError:
    pass


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
        self.offset_x = 0.0
        self.offset_y = 0.0

        # Módulo de simulação atual
        self.current_sim_module = default_simu
        self.sim_file_path = "simu.py" if default_simu else ""

        # Controle de Animação
        self.obj_coords_cache = {}  # Cache para guardar (x, y) de cada objeto visual
        self.active_animations = []  # Lista de animações correndo

        # Setup UI
        self._setup_top_bar()
        self._setup_canvas()

        # Inicializa Simulação
        if self.current_sim_module:
            self.reset_simulation()

    def _setup_top_bar(self):
        # Frame principal da barra
        top_container = ttk.Frame(self)
        top_container.pack(side=tk.TOP, fill=tk.X)

        # Barra de Arquivo (Nova)
        file_bar = ttk.Frame(top_container, padding=5)
        file_bar.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(file_bar, text="Simulation File:").pack(side=tk.LEFT, padx=5)

        self.ent_file = ttk.Entry(file_bar, width=60)
        self.ent_file.pack(side=tk.LEFT, padx=5)
        if self.sim_file_path:
            self.ent_file.insert(0, os.path.abspath(self.sim_file_path))
        self.ent_file.config(state="readonly")

        ttk.Button(file_bar, text="📂 Load...", command=self.browse_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_bar, text="🔄 Reload", command=self.reload_simulation_file).pack(side=tk.LEFT, padx=5)

        # Barra de Controles (Existente)
        bar = ttk.Frame(top_container, padding=5)
        bar.pack(side=tk.TOP, fill=tk.X)

        # Botões de Controle
        btn_frame = ttk.Frame(bar)
        btn_frame.pack(side=tk.LEFT, padx=5)

        ttk.Button(btn_frame, text="▶ Play", command=self.run_simulation).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⏯ Step", command=self.run_single_step).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⏸ Pause", command=self.pause_simulation).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="⏹ Reset", command=self.reset_simulation).pack(side=tk.LEFT, padx=2)

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

        # Break Point Control
        right_frame = ttk.Frame(bar)
        right_frame.pack(side=tk.RIGHT, padx=5)

        ttk.Label(right_frame, text="Break Point:").pack(side=tk.LEFT, padx=(5, 5))
        self.ent_target = ttk.Entry(right_frame, width=10)
        self.ent_target.insert(0, "100")
        self.ent_target.pack(side=tk.LEFT)

    def browse_file(self):
        path = filedialog.askopenfilename(filetypes=[("Python Files", "*.py")])
        if path:
            # Tenta carregar ANTES de atualizar a UI
            if self.load_module_from_path(path):
                self.ent_file.config(state="normal")
                self.ent_file.delete(0, tk.END)
                self.ent_file.insert(0, path)
                self.ent_file.config(state="readonly")
                self.sim_file_path = path
                self.reset_simulation()

    def reload_simulation_file(self):
        path = self.ent_file.get()
        if self.load_module_from_path(path):
            self.sim_file_path = path
            self.reset_simulation()

    def load_module_from_path(self, path):
        if not path or not os.path.exists(path):
            messagebox.showerror("Error", "File not found!")
            return False

        try:
            # Dynamic module loading
            module_name = os.path.splitext(os.path.basename(path))[0]
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                if not hasattr(module, "setup"):
                    messagebox.showerror("Error", "The file must contain a 'setup(env)' function.")
                    return False

                self.current_sim_module = module
                return True
            else:
                messagebox.showerror("Error", "Could not load module spec.")
                return False
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file:\n{e}")
            return False

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
        self.canvas.bind("<MouseWheel>", self.do_zoom)
        self.canvas.bind("<Button-4>", self.do_zoom)
        self.canvas.bind("<Button-5>", self.do_zoom)

    def on_canvas_click(self, event):
        # Transforma coordenadas de tela para coordenadas do canvas (considerando pan/zoom)
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        # Verifica clique nos botões de expandir
        # Procura tags 'expand_btn'
        clicked_items = self.canvas.find_overlapping(cx, cy, cx + 1, cy + 1)
        for item in clicked_items:
            tags = self.canvas.gettags(item)
            for tag in tags:
                if tag.startswith("btn_expand_"):
                    # Extrai o índice do recurso
                    idx = int(tag.split("_")[-1])
                    rec = recursos_rastreados[idx]
                    if hasattr(rec, "is_expanded"):
                        rec.is_expanded = not rec.is_expanded
                        self.draw_scene()
                    return

        # Se não clicou em botão, inicia o Pan
        self.start_pan(event)

    def start_pan(self, event):
        # Guarda a posição inicial do mouse para o Pan manual
        self.pan_start_x = event.x
        self.pan_start_y = event.y

    def do_pan(self, event):
        # Calcula o deslocamento
        dx = event.x - self.pan_start_x
        dy = event.y - self.pan_start_y

        # Move todos os objetos do canvas visualmente
        self.canvas.move("all", dx, dy)

        # Atualiza o offset global para persistir o movimento no próximo redesenho (draw_scene)
        self.offset_x += dx
        self.offset_y += dy

        # Atualiza a referência para o próximo movimento
        self.pan_start_x = event.x
        self.pan_start_y = event.y

    def do_zoom(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)

        if event.delta > 0 or event.num == 4:
            factor = 1.1
        else:
            factor = 0.9

        new_scale = self.scale * factor
        # Allow wider zoom range for "close up" views or "far away" views
        if new_scale < 0.1 or new_scale > 10.0:
            return

        self.scale = new_scale
        self.canvas.scale("all", x, y, factor, factor)
        # We don't restrict scrollregion here anymore to allow free panning
        # self.canvas.configure(scrollregion=self.canvas.bbox("all"))

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
        transferencias_pendentes.clear()
        self.active_animations = []
        self.obj_coords_cache = {}

    def reset_simulation(self):
        self.running = False
        recursos_rastreados.clear()

        # Reseta zoom e pan
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0

        if not self.current_sim_module:
            return

        # Reinicia ambiente SimPy e Setup do usuário
        self.env = simpy.Environment()

        try:
            self.current_sim_module.setup(self.env)
        except Exception as e:
            messagebox.showerror("Simulation Error", f"Error in setup():\n{e}")
            return

        self.ent_target.config(state="normal")
        self.lbl_time.config(text="Time: 0.00")

        self.canvas.delete("all")
        self.draw_scene(initial=True)
        # Center view on reset after specific delay to ensure canvas is ready
        self.after(100, self.center_view)

    def run_simulation(self):
        if not self.running:
            self.running = True
            self.ent_target.config(state="disabled")

            val = self.ent_target.get().strip()
            if not val:
                self.target_time = float("inf")  # Infinite run
            else:
                try:
                    self.target_time = float(val)
                except ValueError:
                    self.target_time = float("inf")

            self.step()

    def run_single_step(self):
        self.running = False
        self.ent_target.config(state="normal")
        try:
            if self.env.peek() != simpy.core.Infinity:
                self.env.step()
                self.draw_scene()

                # Checa se houve movimento e anima
                if transferencias_pendentes:
                    # Calcula duração baseado no slider
                    val = self.scl_speed.get()
                    delay_ms = int(1000 * (0.001 ** (val / 100.0)))
                    delay_ms = max(1, delay_ms)

                    transfers = list(transferencias_pendentes)
                    transferencias_pendentes.clear()
                    self.start_animations(transfers, delay_ms)

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
        # 0 -> 1000ms (Lento)
        # 100 -> 1ms (Rápido)
        # Fórmula: Delay = 1000 * (1/1000)^(val/100)
        delay_ms = int(1000 * (0.001 ** (val / 100.0)))
        # Garante mínimo de 1ms
        delay_ms = max(1, delay_ms)

        # --- PROCESSA ANIMAÇÕES ---
        # Verifica se houve transferências capturadas no monkey_patch
        if transferencias_pendentes:
            # Clona a lista para animar
            transfers = list(transferencias_pendentes)
            transferencias_pendentes.clear()

            # Inicia animação. O delay_ms será o tempo total da animação
            # A animação deve terminar antes do próximo step, ou junto com ele.
            self.start_animations(transfers, delay_ms)

        self.after(delay_ms, self.step)

    def start_animations(self, transfers, duration_ms):
        """Inicia uma animação suave de bolinhas voando entre recursos"""
        # Taxa de atualização: 30fps = ~33ms
        step_time = 33
        frames = max(1, int(duration_ms / step_time))

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
            self.canvas.delete("all")

        self.lbl_time.config(text=f"Time: {self.env.now:.2f}")

        # Posição inicial considerando o PAN acumulado
        start_x = (50 * self.scale) + self.offset_x
        start_y = (50 * self.scale) + self.offset_y

        # Dimensões do Bloco + Margem
        block_w = 300 * self.scale
        block_h = 100 * self.scale
        margin_x = 20 * self.scale
        margin_y = 20 * self.scale

        step_x = block_w + margin_x
        step_y = block_h + margin_y

        total = len(recursos_rastreados)

        # Configurações de Dimensões Base
        base_w = 300 * self.scale
        base_h = 100 * self.scale
        margin = 20 * self.scale

        # Grid System Flexível
        # Em vez de calcular posição fixa (row, col) baseada apenas no índice,
        # precisamos de um "flow layout" que respeite a altura variável dos blocos.
        # Vamos usar um sistema de colunas onde preenchemos a coluna mais curta ou sequencialmente.

        # Para simplificar e manter a identidade visual do pedido anterior (quadrado/retângulo):
        # Vamos definir a largura da coluna fixa, e a altura da linha dinâmica.
        # MAS, alinhar alturas variáveis em grid estrito é difícil.
        # Vamos usar a abordagem: Grid com células, onde um item expandido ocupa células verticais extras.

        if total <= 36:
            cols = math.ceil(math.sqrt(total))
            if cols == 0:
                cols = 1
        else:
            # Fixa 6 linhas (neste caso, altura do grid) -> isso complica se a altura do item varia.
            # Se a altura varia, "6 linhas" deixa de fazer sentido geométrico simples.
            # Vamos manter a lógica de colunas fixas para o modo "quadrado" e
            # linhas fixas para o modo "retângulo", mas adaptando a posição Y.

            # Melhor abordagem: Flow Layout (Masonry simplificado) ou Linha a Linha estrita.
            # Vamos usar Linha a Linha estrita (Row-Major), mas calculando a altura máxima da linha?
            # Não, o usuário quer que "mova os demais blocos".

            # Vamos simplificar: Usar um layout de colunas fixas e empilhar itens (Masonry vertical)
            # ou usar Linhas fixas e empilhar horizontamente?

            # Voltando ao pedido original: "quadrado perfeito" ou "6 de altura".
            # Vamos assumir o Grid Lógico (row, col) calculado anteriormente.
            # Porém, se um item [r, c] expande, ele empurra os itens [r+1, c], [r+2, c] para baixo?
            # Ou ele empurra todo o grid?

            # Abordagem escolhida: Grid Fluido.
            # Calculamos (row, col) lógicos.
            # A posição Y de cada item será baseada na altura acumulada daquela coluna + margem.

            rows_fixed = 6  # Para o modo > 36
            cols_fixed = math.ceil(total / rows_fixed)

            if total <= 36:
                num_cols = math.ceil(math.sqrt(total))
                if num_cols == 0:
                    num_cols = 1
            else:
                # No modo retangulo, cresce para a direita.
                # Então o número de linhas é fixo (6), colunas varia.
                # Mas o preenchimento é "coluna por coluna".
                # Logo, cada COLUNA tem uma lista de itens.
                num_cols = cols_fixed  # Isso é dinâmico no loop
                pass

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
        for i, rec in enumerate(recursos_rastreados):
            # 1. Determina Coluna e Linha Lógicas
            if mode == "SQUARE":
                row_logical = i // grid_dim
                col_logical = i % grid_dim
            else:
                # Mode RECT (Cresce p/ direita, preenche de cima pra baixo)
                row_logical = i % fixed_rows
                col_logical = i // fixed_rows

            # 2. Calcula Altura do Item Atual
            h_atual = base_h
            if hasattr(rec, "is_expanded") and rec.is_expanded:
                # Altura = 2 blocos + margem
                h_atual = (base_h * 2) + margin

            # 3. Calcula Posição X (Baseada na coluna lógica)
            # Largura da coluna é fixa baseada no bloco mais largo (que é padrão)
            col_width = base_w + margin
            x = start_x + (col_logical * col_width)

            # 4. Calcula Posição Y (Baseada no acumulado da coluna OU linha anterior)
            # Se estamos em SQUARE: preenche linha por linha.
            # O problema é que se o item da col 0 expandir, e o da col 1 não, a linha de baixo fica desalinhada visualmente.
            # Para ficar bonito (Masonry), vamos acumular alturas por coluna.

            if col_logical not in col_y_offsets:
                col_y_offsets[col_logical] = start_y

            y = col_y_offsets[col_logical]

            # Desenha
            self._draw_block_for_resource(rec, x, y, i)

            # Atualiza Y da próxima linha nessa coluna
            col_y_offsets[col_logical] += h_atual + margin

    def _draw_block_for_resource(self, rec, x, y, index):
        margin_bg = 0  # Margem interna visual

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
            # Tag 'btn_expand_IDX' identifica qual recurso expandir
            btn_tag = f"btn_expand_{recursos_rastreados.index(rec)}"
            self.canvas.create_rectangle(bx, by, bx + btn_sz, by + btn_sz, fill="white", outline="black", tags=(btn_tag,))
            self.canvas.create_text(bx + btn_sz / 2, by + btn_sz / 2, text=symbol, font=("Segoe UI", int(10 * self.scale)), tags=(btn_tag,))

        # Conteúdo (Títulos)
        font_title = ("Segoe UI", int(12 * self.scale), "bold")
        font_sub = ("Segoe UI", int(9 * self.scale), "italic")

        self.canvas.create_text(x + 10 * self.scale, y + 20 * self.scale, text=rec.nome_visual, anchor="w", font=font_title)
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
        if expanded and items:
            list_y = y + 100 * self.scale  # Começa onde terminaria o bloco normal
            list_h_avail = h - (100 * self.scale) - (10 * self.scale)

            # Fundo da lista
            self.canvas.create_rectangle(x + 10 * self.scale, list_y, x + w - 10 * self.scale, y + h - 10 * self.scale, fill="#f9f9f9", outline="#ccc")

            # Itens
            font_list = ("Consolas", int(9 * self.scale))
            max_lines = 5  # Cabe uns 5 itens
            for k, item in enumerate(items[:max_lines]):
                ly = list_y + (k * 15 * self.scale) + 10 * self.scale
                # Tenta mostrar algo útil do item (str ou repr)
                txt = str(item)
                if len(txt) > 40:
                    txt = txt[:37] + "..."
                self.canvas.create_text(x + 15 * self.scale, ly, text=txt, anchor="w", font=font_list, fill="#333")

            if len(items) > max_lines:
                self.canvas.create_text(x + w / 2, y + h - 15 * self.scale, text=f"...e mais {len(items)-max_lines}", font=("Segoe UI", int(8 * self.scale), "italic"), fill="#888")

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
                cx = x + w - 30 * self.scale
                cy = y + 25 * self.scale
                self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#C0392B", outline="white", width=2)
                self.canvas.create_text(cx, cy, text=str(get_q), fill="white", font=badge_font)
                self.canvas.create_text(cx, cy + r + 8 * self.scale, text="FILA", font=label_font)
