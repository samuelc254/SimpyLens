import simpy
import simpylens
import random
import logging
from dataclasses import dataclass
from typing import Optional

# Configuração de log padrão do engenheiro (antes da sua biblioteca)
logging.basicConfig(level=logging.INFO, format="[%(sim_time)07.2f] %(levelname)s - %(message)s")

# --- Definições de Domínio ---


@dataclass
class Part:
    id: int
    material_type: str
    quality_grade: Optional[str] = None
    creation_time: float = 0.0


# --- Classes de Simulação ---


class AdvancedManufacturingCell:
    """Modela uma célula de manufatura com Impressoras 3D industriais, CNCs e um robô AGV."""

    def __init__(self, env: simpy.Environment):
        self.env = env

        # 1. Container: Matéria-prima contínua (Pó de Titânio em kg)
        self.titanium_powder = simpy.Container(env, capacity=1000, init=1000)

        # 2. PreemptiveResource: Máquinas principais que podem sofrer manutenção de emergência
        self.slm_printers = simpy.PreemptiveResource(env, capacity=3)

        # 3. Resource padrão: Usinagem de acabamento
        self.cnc_mills = simpy.Resource(env, capacity=2)

        # 4. FilterStore: Armazém inteligente para peças finalizadas
        self.warehouse = simpy.FilterStore(env, capacity=500)

        # Inicia processos em background
        self.env.process(self.maintenance_loop())
        self.env.process(self.powder_restock_monitor())
        self.env.process(self.shipping_department())

    def log(self, msg: str):
        logging.info(msg, extra={"sim_time": self.env.now})

    def powder_restock_monitor(self):
        """Monitora o nível de pó de titânio e faz pedidos de reabastecimento."""
        while True:
            if self.titanium_powder.level < 200:
                self.log("Nível de titânio crítico. Solicitando reabastecimento...")
                yield self.env.timeout(15)  # Tempo de entrega do fornecedor interno
                amount_to_fill = self.titanium_powder.capacity - self.titanium_powder.level
                yield self.titanium_powder.put(amount_to_fill)
                self.log(f"Silo de titânio reabastecido com {amount_to_fill}kg.")

            # Aguarda um tempo antes de checar novamente ou é acordado
            yield self.env.timeout(5)

    def maintenance_loop(self):
        """Gera falhas aleatórias nas impressoras SLM que interrompem a produção."""
        while True:
            # Tempo entre falhas (MTBF)
            yield self.env.timeout(random.expovariate(1.0 / 120.0))

            if self.slm_printers.users:
                # Escolhe uma impressora ativa aleatoriamente para quebrar
                victim_req = random.choice(self.slm_printers.users)
                self.log(f"[MANUTENÇÃO] Falha detectada! Interrompendo processo atual...")

                # Preempção: Requisita o recurso com prioridade máxima (0) e modo preemptivo
                with self.slm_printers.request(priority=0, preempt=True) as maint_req:
                    yield maint_req
                    self.log("[MANUTENÇÃO] Técnico assumiu a máquina. Reparando...")
                    yield self.env.timeout(random.uniform(10, 30))  # Tempo de reparo (MTTR)
                    self.log("[MANUTENÇÃO] Máquina reparada e devolvida à produção.")

    def shipping_department(self):
        """Departamento de envios que busca peças específicas no armazém."""
        while True:
            yield self.env.timeout(random.uniform(40, 80))
            self.log("Expedição procurando um lote de peças 'Grade A'...")

            # Utiliza FilterStore para pegar apenas peças com qualidade Grade A
            get_req = self.warehouse.get(lambda part: part.quality_grade == "Grade A")

            # Timeout lógico: Se não achar a peça em 20 minutos, desiste da busca
            timeout = self.env.timeout(20)
            result = yield get_req | timeout

            if get_req in result:
                part = result[get_req]
                lead_time = self.env.now - part.creation_time
                self.log(f"Peça {part.id} expedida com sucesso! Lead time: {lead_time:.2f} min.")
            else:
                self.log("Expedição cancelada: Nenhuma peça 'Grade A' disponível no tempo limite.")
                get_req.cancel()


def production_order(env: simpy.Environment, name: str, part_id: int, cell: AdvancedManufacturingCell):
    """Ciclo de vida de uma ordem de produção individual."""
    part = Part(id=part_id, material_type="Titanium", creation_time=env.now)
    cell.log(f"Ordem {name} iniciada para a peça {part.id}.")

    # 1. Consumo de material (Container)
    powder_needed = random.uniform(2.5, 4.0)
    yield cell.titanium_powder.get(powder_needed)

    # 2. Impressão 3D (PreemptiveResource com tratamento de Interrupção)
    printed = False
    while not printed:
        try:
            # Prioridade normal (1). A manutenção usa 0.
            with cell.slm_printers.request(priority=1) as print_req:
                yield print_req
                cell.log(f"Ordem {name} alocou uma impressora SLM.")
                # Tempo de impressão
                yield env.timeout(random.uniform(25.0, 45.0))
                printed = True
                cell.log(f"Ordem {name} concluiu impressão.")

        except simpy.Interrupt:
            # Processo foi interrompido por uma quebra de máquina
            cell.log(f"Ordem {name} sofreu interrupção na impressora. Peça danificada, reiniciando impressão...")
            # Devolve o material perdido e pega novo
            yield cell.titanium_powder.get(powder_needed)

    # 3. Usinagem CNC (Resource padrão com condição combinada - AnyOf)
    with cell.cnc_mills.request() as cnc_req:
        patience_timer = env.timeout(60)
        # O processo aguarda o CNC ou perde a paciência (ex: peça esfriou demais)
        results = yield cnc_req | patience_timer

        if cnc_req in results:
            cell.log(f"Ordem {name} alocou um CNC.")
            yield env.timeout(random.uniform(10.0, 15.0))
        else:
            cell.log(f"Ordem {name} abortada. Tempo de espera para o CNC excedido.")
            cnc_req.cancel()
            return  # Encerra o processo prematuramente

    # 4. Inspeção de Qualidade e Armazenamento (FilterStore)
    part.quality_grade = "Grade A" if random.random() > 0.2 else "Grade B"
    yield cell.warehouse.put(part)
    cell.log(f"Ordem {name} concluída. Peça {part.id} ({part.quality_grade}) enviada ao armazém.")


def order_generator(env: simpy.Environment, cell: AdvancedManufacturingCell):
    """Gera novas ordens de produção continuamente."""
    order_id = 1
    while True:
        yield env.timeout(random.expovariate(1.0 / 15.0))  # Chega uma ordem a cada 15 min em média
        env.process(production_order(env, f"ORD-{order_id:04d}", order_id, cell))
        order_id += 1


# --- Execução da Simulação --- exemplo de main comum para rodar a simulação sem a interface gráfica
# if __name__ == "__main__":
#     random.seed(42)
#     env = simpy.Environment()
#     factory_cell = AdvancedManufacturingCell(env)

#     env.process(order_generator(env, factory_cell))

#     logging.info("--- Iniciando Simulação da Fábrica ---")
#     env.run(until=400) # Roda por 400 minutos simulados
#     logging.info("--- Simulação Concluída ---")


# exemplo de main para rodar a simulação com a interface gráfica
def setup(env):
    factory_cell = AdvancedManufacturingCell(env)
    env.process(order_generator(env, factory_cell))


if __name__ == "__main__":

    sim_view = simpylens.Viewer(model=setup)
    sim_view.mainloop()
