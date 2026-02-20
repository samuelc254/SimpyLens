import simpy
import random
import sys
import os


from simpy_visualizer import SimPyVisualizer

# CONFIGURAÇÃO DE LOGS (True = Mostra mensagens, False = Silencia)
VERBOSE = False

if not VERBOSE:
    # Redefine a função print para não fazer nada neste módulo
    def print(*args, **kwargs):
        pass


# Variável global para métricas
total_fabricados = 0


def fabrica(env):
    global total_fabricados
    # ... (rest of the logic, but wait, I need to copy paste or rewrite it) ...
    # Instead of copying, I can just import it if I kept simu.py, but I plan to move it.
    # So I must copy the content.

    # --- RECURSOS (MÁQUINAS E OPERADORES) ---
    moldagem = simpy.Resource(env, capacity=3)  # Aumentei para 3 máquinas
    esmaltacao = simpy.Resource(env, capacity=2)  # Nova etapa
    pintura = simpy.Resource(env, capacity=2)  # Aumentei a capacidade

    # --- STORES (PROCESSOS EM LOTE OU COMPLEXOS) ---
    forno = simpy.Store(env, capacity=5)  # Mantém o lote de 5

    # --- CONTAINERS (ESTOQUES DE FLUIDOS/GRANEL) ---
    deposito_argila = simpy.Container(env, capacity=100, init=20)  # Começa com pouca argila
    expedicao = simpy.Container(env, capacity=1000, init=0)  # Estoque final

    # Inicia processos auxiliares
    env.process(abastecedor_argila(env, deposito_argila))

    id_pote = 1

    while True:
        # Chegada de pedidos
        tempo_chegada = max(0.5, random.normalvariate(2, 0.5))
        yield env.timeout(tempo_chegada)

        pote_atual = {"id": id_pote, "tipo": random.choice(["Vaso", "Prato", "Caneca"]), "chegada": env.now}

        env.process(processar_pote(env, pote_atual, moldagem, esmaltacao, forno, pintura, deposito_argila, expedicao))
        id_pote += 1


def abastecedor_argila(env, deposito):
    """Processo independente que reabastece o estoque de argila periodicamente"""
    while True:
        yield env.timeout(15)  # A cada 15 min
        if deposito.level < 50:
            yield deposito.put(40)
            print(f"[Sistema] Reabastecimento de Argila (+40). Estoque: {deposito.level}")


def processar_pote(env, pote, moldagem, esmaltacao, forno, pintura, deposito_argila, expedicao):
    global total_fabricados
    id_pote = pote["id"]

    # --- ETAPA 1: MOLDAGEM (Consome Argila) ---
    # Primeiro pega argila
    yield deposito_argila.get(2)  # 2kg por pote

    with moldagem.request() as req:
        yield req
        tempo_mold = random.uniform(3, 5)
        yield env.timeout(tempo_mold)

    # --- ETAPA 2: ESMALTAÇÃO ---
    with esmaltacao.request() as req:
        yield req
        yield env.timeout(2)

    # --- ETAPA 3: FORNO (Lote) ---
    # Põe no forno
    yield forno.put(pote)

    # Se forno cheio, queima
    if len(forno.items) >= 5:
        # Define líder do lote
        print(f"[Forno] Iniciando queima de lote com 5 itens.")
        yield env.timeout(10)  # Tempo de queima

        # Esvazia o forno
        lote_pronto = []
        for _ in range(5):
            item = yield forno.get()
            lote_pronto.append(item)

        # Dispara evento para liberar quem está esperando
        if hasattr(forno, "batch_ready_event"):
            forno.batch_ready_event.succeed(value=lote_pronto)
            forno.batch_ready_event = env.event()
    else:
        # Seguidores esperam
        if not hasattr(forno, "batch_ready_event"):
            forno.batch_ready_event = env.event()
        yield forno.batch_ready_event

    # --- ETAPA 4: PINTURA FINAL ---
    with pintura.request() as req:
        yield req
        yield env.timeout(2)

    # --- ETAPA 5: EXPEDIÇÃO ---
    # Deposita o produto final no estoque
    yield expedicao.put(1)

    total_fabricados += 1
    print(f"[Pote {id_pote}] CONCLUÍDO e Estocado. (Total: {total_fabricados})")


def setup(env):
    env.process(fabrica(env))


if __name__ == "__main__":
    # Inicia a visualização
    viz = SimPyVisualizer(setup_func=setup, title="Factory Simulation Example")
    viz.mainloop()
