import simpy
import random
import logging
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logging.basicConfig(level=logging.INFO, format="[%(sim_time)07.2f] %(levelname)s - %(message)s")

# --- Classes de Domínio ---


@dataclass
class Wafer:
    id: str
    layer_count: int = 0
    is_defective: bool = False


@dataclass
class Lot:
    id: str
    priority: int
    wafers: List[Wafer] = field(default_factory=list)
    creation_time: float = 0.0


# --- Motor da Fábrica ---


class SemiconductorFab:
    def __init__(self, env: simpy.Environment):
        self.env = env

        # --- Recursos Estáticos de Instalação (1 a 12) ---

        # Insumos Contínuos (Containers)
        self.silicon_inventory = simpy.Container(env, capacity=5000, init=5000)  # 1
        self.photoresist = simpy.Container(env, capacity=1000, init=1000)  # 2
        self.ultra_pure_water = simpy.Container(env, capacity=10000, init=10000)  # 3
        self.nitrogen_gas = simpy.Container(env, capacity=5000, init=5000)  # 4

        # Máquinas de Processamento (Resources e PreemptiveResources)
        self.steppers = simpy.PreemptiveResource(env, capacity=2)  # 5 (Fotolitografia - Crítico)
        self.etchers = simpy.Resource(env, capacity=3)  # 6 (Corrosão)
        self.ion_implanters = simpy.Resource(env, capacity=2)  # 7 (Dopagem)
        self.furnaces = simpy.Resource(env, capacity=4)  # 8 (Difusão térmica)
        self.cmp_polishers = simpy.Resource(env, capacity=2)  # 9 (Polimento Químico-Mecânico)

        # Logística e Qualidade (Stores e FilterStores)
        self.agv_fleet = simpy.Resource(env, capacity=5)  # 10 (Robôs de transporte)
        self.metrology_queue = simpy.FilterStore(env, capacity=100)  # 11 (Inspeção com filtros)
        self.finished_goods = simpy.Store(env, capacity=1000)  # 12 (Armazém final)

        # --- Rastreio de Recursos Dinâmicos ---
        self.active_foups: Dict[str, simpy.Store] = {}  # 13+ (Recipientes criados sob demanda)
        self.dynamic_inspectors: Dict[str, simpy.Resource] = {}  # 14+ (Inspetores contratados sob demanda)

        # Processos de background
        self.env.process(self.facility_monitor())
        self.env.process(self.stepper_maintenance())
        self.env.process(self.dynamic_inspector_manager())

    def log(self, msg: str):
        logging.info(msg, extra={"sim_time": self.env.now})

    # --- Background Routines ---

    def facility_monitor(self):
        """Mantém os containers de fluidos e gases abastecidos."""
        while True:
            if self.photoresist.level < 200:
                yield self.photoresist.put(800)
                self.log("Instalação: Photoresist reabastecido.")
            if self.ultra_pure_water.level < 2000:
                yield self.ultra_pure_water.put(8000)
            yield self.env.timeout(10)

    def stepper_maintenance(self):
        """Preempção caótica: Máquinas de litografia quebram muito e exigem reparo imediato."""
        while True:
            yield self.env.timeout(random.expovariate(1.0 / 60.0))
            if self.steppers.users:
                self.log("[FALHA] Stepper quebrou! Iniciando preempção para manutenção.")
                with self.steppers.request(priority=0, preempt=True) as maint_req:
                    yield maint_req
                    yield self.env.timeout(random.uniform(15, 45))
                    self.log("[FALHA] Stepper reparado.")

    def dynamic_inspector_manager(self):
        """
        Cria e destroi recursos dinamicamente baseado na fila do FilterStore.
        Isso é um pesadelo para visualizadores estáticos.
        """
        while True:
            queue_size = len(self.metrology_queue.items)
            active_dyn = len(self.dynamic_inspectors)

            # Se a fila cresce, aloca dinamicamente um novo recurso de inspeção
            if queue_size > 10 and active_dyn < 3:
                res_id = f"DynInspector_{uuid.uuid4().hex[:6]}"
                self.dynamic_inspectors[res_id] = simpy.Resource(self.env, capacity=1)
                self.log(f"[SCALING] Fila de metrologia alta ({queue_size}). Criado recurso dinâmico: {res_id}")

            # Se a fila zera, desaloca recursos dinâmicos ociosos
            elif queue_size == 0 and active_dyn > 0:
                to_remove = []
                for res_id, res in self.dynamic_inspectors.items():
                    if res.count == 0:  # Ninguém usando
                        to_remove.append(res_id)

                for res_id in to_remove:
                    del self.dynamic_inspectors[res_id]  # O Garbage Collector do Python assume daqui
                    self.log(f"[SCALING] Descomissionando recurso dinâmico ocioso: {res_id}")

            yield self.env.timeout(20)


def process_lot(env: simpy.Environment, fab: SemiconductorFab, lot: Lot):
    """Ciclo de vida de um lote de Wafers. Flui por múltiplos recursos com lógica combinada."""
    fab.log(f"Lote {lot.id} iniciado (Prioridade {lot.priority}).")

    # 1. Criação de Recurso Dinâmico: FOUP (Front Opening Unified Pod)
    # Cada lote ganha um 'Store' exclusivo temporário para carregar seus wafers fisicamente.
    foup_id = f"FOUP_{lot.id}"
    fab.active_foups[foup_id] = simpy.Store(env, capacity=25)

    # Consome silício para criar os wafers e coloca no FOUP dinâmico
    yield fab.silicon_inventory.get(25)
    for i in range(25):
        wafer = Wafer(id=f"{lot.id}-W{i}")
        lot.wafers.append(wafer)
        yield fab.active_foups[foup_id].put(wafer)

    fab.log(f"Lote {lot.id} carregado no {foup_id} dinâmico.")

    layers_target = 3
    for layer in range(layers_target):
        # 2. Evento Combinado (AllOf - Lógica AND)
        # Precisa simultaneamente de água ultrapura, gás nitrogênio E do robô de transporte.
        # Se um faltar, ele trava esperando os 3.
        req_upw = fab.ultra_pure_water.get(50)
        req_n2 = fab.nitrogen_gas.get(20)

        with fab.agv_fleet.request() as agv_req:
            yield req_upw & req_n2 & agv_req
            fab.log(f"Lote {lot.id} em transporte seguro para camada {layer+1}.")
            yield env.timeout(random.uniform(2, 5))

        # 3. Processo Crítico com Interrupção (Fotolitografia)
        completed_litho = False
        while not completed_litho:
            try:
                yield fab.photoresist.get(10)
                # Note a prioridade: Lotes urgentes passam na frente de lotes normais
                with fab.steppers.request(priority=lot.priority) as step_req:
                    yield step_req
                    fab.log(f"Lote {lot.id} no Stepper.")
                    yield env.timeout(random.uniform(10, 20))
                    completed_litho = True
            except simpy.Interrupt:
                fab.log(f"Lote {lot.id} abortado no Stepper por manutenção! Retrabalhando camada...")
                # Lógica de retrabalho: Apenas espera um pouco e o loop While tenta de novo

        # 4. Processamento Padrão Sequencial
        with fab.etchers.request() as etch_req:
            yield etch_req
            yield env.timeout(15)

        with fab.ion_implanters.request() as ion_req:
            yield ion_req
            yield env.timeout(25)

    # 5. Metrologia e Qualidade (FilterStore)
    # Coloca o lote inteiro para inspeção
    yield fab.metrology_queue.put(lot)

    # Simula a inspeção lendo os dados do lote.
    # Aqui, a expedição pega o lote de volta baseando-se na sua ID usando lambda.
    inspect_req = fab.metrology_queue.get(lambda l: l.id == lot.id)

    # 6. Uso Opcional de Recurso Dinâmico (AnyOf - Lógica OR)
    # Tenta usar um inspetor dinâmico (se existir) OU aguarda 30 minutos na fila normal
    timeout_event = env.timeout(30)

    dynamic_req = None
    if fab.dynamic_inspectors:
        # Pega qualquer inspetor dinâmico disponível
        inspector_id, dyn_res = random.choice(list(fab.dynamic_inspectors.items()))
        dynamic_req = dyn_res.request()

        results = yield dynamic_req | timeout_event

        if dynamic_req in results:
            fab.log(f"Lote {lot.id} inspecionado via recurso dinâmico {inspector_id}.")
            yield env.timeout(5)
            dyn_res.release(dynamic_req)
        else:
            dynamic_req.cancel()

    # Garante que o item saiu do FilterStore
    inspected_lot = yield inspect_req

    # 7. Destruição do Recurso Dinâmico e Finalização
    # Transfere os wafers do FOUP dinâmico para o armazém final
    for _ in range(25):
        w = yield fab.active_foups[foup_id].get()
        yield fab.finished_goods.put(w)

    # Remove a referência do dicionário. Para o SimPy e para o Python, este Store "morre" aqui.
    del fab.active_foups[foup_id]

    lead_time = env.now - inspected_lot.creation_time
    fab.log(f"Lote {lot.id} FINALIZADO. FOUP destruído. Lead time: {lead_time:.2f} min.")


def lot_generator(env: simpy.Environment, fab: SemiconductorFab):
    """Injeta lotes de produção continuamente."""
    lot_counter = 1
    while True:
        # Chegada de novos lotes (distribuição exponencial)
        yield env.timeout(random.expovariate(1.0 / 25.0))
        priority = 1 if random.random() > 0.1 else 2  # 10% dos lotes são alta prioridade

        new_lot = Lot(id=f"L{lot_counter:04d}", priority=priority, creation_time=env.now)
        env.process(process_lot(env, fab, new_lot))
        lot_counter += 1


# --- Execução --- exemplo de main comum para rodar a simulação sem a interface gráfica
# if __name__ == "__main__":
#     random.seed(99)
#     env = simpy.Environment()
#     fab = SemiconductorFab(env)

#     env.process(lot_generator(env, fab))

#     logging.info("--- Iniciando Simulação Wafer Fab ---")
#     env.run(until=300) # Roda por 300 minutos

#     logging.info("--- Simulação Concluída ---")
#     logging.info(f"FOUPs Dinâmicos ainda vivos na memória: {len(fab.active_foups)}")
#     logging.info(f"Inspetores Dinâmicos ainda vivos na memória: {len(fab.dynamic_inspectors)}")
#     logging.info(f"Wafers no armazém final: {len(fab.finished_goods.items)}")


# exemplo de main para rodar a simulação com a interface gráfica
def setup(env):
    fab = SemiconductorFab(env)
    env.process(lot_generator(env, fab))


if __name__ == "__main__":
    from simpy_visualizer import SimPyVisualizer

    viz = SimPyVisualizer(setup_func=setup, title="Semiconductor Fab Complex Simulation")
    viz.mainloop()
