# simu.py
import simpy
import random

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
        yield env.timeout(30)  # Caminhão chega a cada 30 min
        qtd = 40
        espaco_livre = deposito.capacity - deposito.level
        carga = min(qtd, espaco_livre)

        if carga > 0:
            print(f"[Sistema] Caminhão chegou! Reabastecendo {carga}kg de argila.")
            yield deposito.put(carga)
        else:
            print(f"[Sistema] Depósito cheio. Caminhão retornou.")


def processar_pote(env, pote, moldagem, esmaltacao, forno, pintura, deposito_argila, expedicao):
    global total_fabricados
    id_pote = pote["id"]
    tipo = pote["tipo"]

    # Define consumo baseando no tipo
    consumo = 2 if tipo == "Vaso" else 1

    # --- ETAPA 0: CONSUMO DE MATÉRIA PRIMA ---
    # Se não tiver argila, o processo trava aqui e aparece no visualizador como "WAIT" no Container
    yield deposito_argila.get(consumo)

    print(f"[Pote {id_pote} - {tipo}] Iniciado. Argila consumida.")

    # --- ETAPA 1: MOLDAGEM ---
    with moldagem.request() as req:
        yield req
        yield env.timeout(random.uniform(3, 6))

    # Chance de quebra (Simulação de refugo/perda)
    if random.random() < 0.05:
        print(f"[Pote {id_pote}] QUEBROU na moldagem! Descartado.")
        return  # Sai do processo

    # --- ETAPA 2: ESMALTAÇÃO (NOVA) ---
    with esmaltacao.request() as req:
        yield req
        yield env.timeout(random.uniform(2, 4))

    # --- ETAPA 3: FORNO (BATCH) ---
    yield forno.put(pote)
    print(f"[Pote {id_pote}] Aguardando forno... ({len(forno.items)}/5)")

    # Lógica do Forno (Líder do lote)
    if len(forno.items) == forno.capacity:
        print(f"--- FORNO LIGADO (Batch) ---")
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

    global total_fabricados
    total_fabricados += 1
    print(f"[Pote {id_pote}] CONCLUÍDO e Estocado. (Total: {total_fabricados})")


def setup(env):
    env.process(fabrica(env))
