import simpy
import random
import sys
import os

from simpy_visualizer import SimPyVisualizer

# CONFIGURAÇÃO DE LOGS
VERBOSE = False

if not VERBOSE:

    def print(*args, **kwargs):
        pass


# Métricas Globais
pacientes_atendidos = 0


def hospital_run(env):
    global pacientes_atendidos

    # ---------------------------------------------------------
    # 1. Definição dos Recursos do Hospital
    # ---------------------------------------------------------

    # Recepção: Primeiro ponto de contato
    recepcao = simpy.Resource(env, capacity=3)

    # Triagem: Enfermeiros classificam risco
    triagem = simpy.Resource(env, capacity=2)

    # Sala de Espera Principal: Onde os pacientes aguardam chamados
    # Usamos Store para visualizar os pacientes (objetos) esperando
    sala_espera = simpy.Store(env, capacity=50)

    # Consultórios Médicos
    consultorios = simpy.Resource(env, capacity=5)

    # Laboratório de Exames (Raio-X, Sangue)
    laboratorio = simpy.Resource(env, capacity=2)

    # Banco de Sangue (Container): Consumido em cirurgias
    banco_sangue = simpy.Container(env, capacity=100, init=80)

    # Farmácia Central (Container): Estoque de medicamentos
    farmacia = simpy.Container(env, capacity=500, init=400)

    # Centro Cirúrgico
    centro_cirurgico = simpy.Resource(env, capacity=1)

    # Sala de Recuperação (Pós-operatório)
    sala_recuperacao = simpy.Store(env, capacity=5)

    # Faturamento / Alta
    faturamento = simpy.Resource(env, capacity=2)

    # Processo auxiliar: Reabastecimento de Sangue e Remédios
    env.process(abastecimento_logistico(env, banco_sangue, farmacia))

    id_paciente = 1

    while True:
        # Chegada de pacientes (exponencial)
        yield env.timeout(random.expovariate(1.0 / 2.0))  # Chega um a cada ~2 min

        tipo_paciente = random.choice(["Normal", "Normal", "Normal", "Urgente"])
        paciente = {"id": id_paciente, "tipo": tipo_paciente, "chegada": env.now}

        env.process(processo_paciente(env, paciente, recepcao, triagem, sala_espera, consultorios, laboratorio, banco_sangue, farmacia, centro_cirurgico, sala_recuperacao, faturamento))
        id_paciente += 1


def abastecimento_logistico(env, sangue, remedios):
    """Caminhão de suprimentos chega periodicamente"""
    while True:
        yield env.timeout(100)
        # Reabastece sangue se necessário
        falta_sangue = sangue.capacity - sangue.level
        if falta_sangue > 10:
            yield sangue.put(min(20, falta_sangue))
            print(f"[Logística] Sangue reabastecido.")

        # Reabastece farmácia
        yield remedios.put(50)
        print(f"[Logística] Farmácia reabastecida.")


def processo_paciente(env, p, recepcao, triagem, sala_espera, consultorio, lab, sangue, farmacia, cirurgia, recuperacao, faturamento):
    global pacientes_atendidos
    pid = p["id"]
    tipo = p["tipo"]

    print(f"Paciente {pid} ({tipo}) chegou.")

    # 1. Recepção
    with recepcao.request() as req:
        yield req
        yield env.timeout(random.uniform(1, 3))

    # 2. Triagem
    with triagem.request() as req:
        yield req
        yield env.timeout(random.uniform(2, 5))

    # 3. Aguarda na Sala de Espera (Store)
    # Coloca o paciente na "Cadeira"
    yield sala_espera.put(f"P{pid}")

    # Simula espera até o médico chamar (recurso liberar)
    # A lógica aqui é invertida: o paciente ocupa espaço na sala,
    # tenta pegar o médico, e quando consegue, sai da sala.

    # Tenta pegar um médico
    req_medico = consultorio.request()
    yield req_medico  # Espera o médico liberar

    # Sai da sala de espera (libera a cadeira)
    yield sala_espera.get()

    # 4. Consulta Médica
    # Já temos o request feito acima
    t_consulta = random.uniform(5, 15)
    yield env.timeout(t_consulta)

    # Médico define o destino
    chance = random.random()

    if chance < 0.2:
        # Caso Grave: Cirurgia
        consultorio.release(req_medico)  # Libera o médico
        print(f"Paciente {pid} encaminhado para CIRURGIA.")

        # Consome Sangue
        if sangue.level >= 2:
            yield sangue.get(2)

        with cirurgia.request() as req_cir:
            yield req_cir
            yield env.timeout(random.uniform(20, 40))

        # Recuperação
        yield recuperacao.put(f"P{pid}-Recup")
        yield env.timeout(15)  # Tempo descansando
        yield recuperacao.get()

    elif chance < 0.5:
        # Exames
        consultorio.release(req_medico)  # Libera médico

        with lab.request() as req_lab:
            yield req_lab
            yield env.timeout(random.uniform(5, 10))

        # Retorno rápido ao médico (fura fila ou nova consulta? vamos simplificar: vai pra farmacia direto)
        # Consome contraste/insumos da farmacia para o exame
        yield farmacia.get(1)

    else:
        # Caso Simples: Receita e Casa
        consultorio.release(req_medico)
        yield env.timeout(1)

    # 5. Farmácia (Pegar remédios para casa)
    yield farmacia.get(random.randint(1, 3))

    # 6. Pagamento / Alta
    with faturamento.request() as req:
        yield req
        yield env.timeout(random.uniform(2, 4))

    pacientes_atendidos += 1
    print(f"Paciente {pid} teve ALTA.")


def setup(env):
    env.process(hospital_run(env))


if __name__ == "__main__":
    # Inicia a visualização
    viz = SimPyVisualizer(setup_func=setup, title="Hospital Complex Simulation")
    viz.mainloop()
