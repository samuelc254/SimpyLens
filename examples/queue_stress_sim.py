import random

import simpy
from simpylens import Viewer


VERBOSE = False

if not VERBOSE:

    def print(*args, **kwargs):
        pass


BATCH_SIZE = 16


def setup(env):
    """
    Cenário de estresse leve para UI com apenas:
    - 2 Resources
    - 2 Stores
    - 2 Containers

    Mantém:
    - fila de request em Resource
    - put_queue e get_queue em Store
    - put_queue e get_queue em Container
    - movimentação em lote (dezenas no mesmo tick)
    """

    # --- 2 Resources ---
    machine = simpy.Resource(env, capacity=1)
    shipper = simpy.Resource(env, capacity=1)

    # --- 2 Stores ---
    input_queue = simpy.Store(env, capacity=10)
    oven_buffer = simpy.Store(env, capacity=26)
    oven_buffer.finished_firing = env.event()
    oven_buffer.batch_ready_event = env.event()

    # --- 2 Containers ---
    raw_material = simpy.Container(env, capacity=220, init=70)
    finished_units = simpy.Container(env, capacity=60, init=0)

    # Gera pressão real no input_queue (sem reciclar o mesmo item)
    env.process(order_generator(env, input_queue))

    # Workers competem por machine (Resource queue)
    for worker_id in range(6):
        env.process(machine_worker(env, worker_id, machine, input_queue, oven_buffer, raw_material, finished_units))

    # Forno em lote com eventos (estilo basic_sim)
    env.process(batch_oven_manager(env, oven_buffer))

    # Saída lenta + probes para get_queue em finished_units
    env.process(shipping_consumer(env, shipper, finished_units))
    for probe_id in range(10):
        env.process(finished_hungry_probe(env, probe_id, finished_units))

    # Força put_queue/get_queue no raw_material
    env.process(raw_refill_pressure(env, raw_material))
    for drain_id in range(6):
        env.process(raw_hungry_drain(env, drain_id, raw_material))


def order_generator(env, input_queue):
    order_id = 1
    while True:
        # alta taxa para pressionar put_queue
        yield env.timeout(random.uniform(0.001, 0.007))
        job = {
            "id": order_id,
            "units": random.randint(4, 7),
            "created_at": env.now,
        }
        yield input_queue.put(job)
        order_id += 1


def machine_worker(env, worker_id, machine, input_queue, oven_buffer, raw_material, finished_units):
    while True:
        job = yield input_queue.get()
        # força get_queue no container de matéria-prima
        yield raw_material.get(4)

        with machine.request() as req:
            yield req
            yield env.timeout(random.uniform(0.9, 1.8))

        # envia várias peças para forno com espera por evento de liberação em lote
        for unit in range(job["units"] * 2):
            piece = {
                "id": f"J{job['id']}-W{worker_id}-U{unit}",
                "t0": job["created_at"],
            }
            env.process(oven_piece_process(env, piece, oven_buffer, finished_units))


def batch_oven_manager(env, oven_buffer):
    """
    Padrão estilo forno do basic_sim:
    - espera lote encher
    - processa
    - dispara eventos para liberar o lote de uma vez
    """
    while True:
        while len(oven_buffer.items) < BATCH_SIZE:
            yield env.timeout(0.05)

        yield env.timeout(2)

        fired_batch = []
        for _ in range(BATCH_SIZE):
            item = yield oven_buffer.get()
            fired_batch.append(item)

        oven_buffer.finished_firing.succeed()
        oven_buffer.batch_ready_event.succeed(value=fired_batch)

        oven_buffer.finished_firing = env.event()
        oven_buffer.batch_ready_event = env.event()


def oven_piece_process(env, piece, oven_buffer, finished_units):
    """
    Cada peça entra no forno e espera o lote ser liberado via eventos.
    A saída só ocorre quando a peça pertence ao batch liberado.
    """
    yield oven_buffer.put(piece)

    while True:
        yield oven_buffer.finished_firing
        ready_batch = yield oven_buffer.batch_ready_event
        if piece in ready_batch:
            break

    yield finished_units.put(1)


def shipping_consumer(env, shipper, finished_units):
    while True:
        yield finished_units.get(2)
        with shipper.request() as req:
            yield req
            yield env.timeout(random.uniform(2.6, 4.5))


def finished_hungry_probe(env, probe_id, finished_units):
    """Consumidores extras para elevar get_queue no container final."""
    while True:
        yield env.timeout(random.uniform(0.05, 0.2))
        yield finished_units.get(1)
        _ = probe_id


def raw_refill_pressure(env, raw_material):
    """Força put_queue no container ao tentar reabastecer em blocos grandes."""
    while True:
        yield env.timeout(0.5)
        if raw_material.level > 160:
            yield raw_material.put(80)
        else:
            yield raw_material.put(50)


def raw_hungry_drain(env, drain_id, raw_material):
    while True:
        yield env.timeout(random.uniform(0.08, 0.18))
        yield raw_material.get(5)
        _ = drain_id


if __name__ == "__main__":
    random.seed(7)
    viewer = Viewer(setup_func=setup, title="Queue Stress (2x Resource/Store/Container)")
    viewer.mainloop()
