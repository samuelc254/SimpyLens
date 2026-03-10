"""Wafer Fabrication Example.

Origin:
    Original SimpyLens example.

Credits:
    - SimpyLens maintainers.

Covers:
    - Complex multi-resource flow (`Resource`, `PreemptiveResource`)
    - Bulk inventories (`Container`)
    - Dynamic resources and queues (`Store`, `FilterStore`)
    - Combined events (`AllOf`/`AnyOf` style conditions)

Scenario:
    A semiconductor fabrication line processes lots through transport,
    lithography, etching, implantation, metrology, and final warehousing,
    including dynamic inspector scaling and maintenance preemption.
"""

import simpy
import simpylens
import random
import logging
import uuid
from dataclasses import dataclass, field
from typing import List, Dict

logging.basicConfig(level=logging.INFO, format="[%(sim_time)07.2f] %(levelname)s - %(message)s")

# Domain classes.


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


# Factory engine.


class SemiconductorFab:
    def __init__(self, env: simpy.Environment):
        self.env = env

        # Static facility resources (1 to 12).

        # Continuous supplies (Containers).
        self.silicon_inventory = simpy.Container(env, capacity=5000, init=5000)  # 1
        self.photoresist = simpy.Container(env, capacity=1000, init=1000)  # 2
        self.ultra_pure_water = simpy.Container(env, capacity=10000, init=10000)  # 3
        self.nitrogen_gas = simpy.Container(env, capacity=5000, init=5000)  # 4

        # Processing machines (Resources and PreemptiveResources).
        self.steppers = simpy.PreemptiveResource(env, capacity=2)  # 5 (Fotolitografia - Crítico)
        self.etchers = simpy.Resource(env, capacity=3)  # 6 (Corrosão)
        self.ion_implanters = simpy.Resource(env, capacity=2)  # 7 (Dopagem)
        self.furnaces = simpy.Resource(env, capacity=4)  # 8 (Difusão térmica)
        self.cmp_polishers = simpy.Resource(env, capacity=2)  # 9 (Polimento Químico-Mecânico)

        # Logistics and quality control (Stores and FilterStore).
        self.agv_fleet = simpy.Resource(env, capacity=5)  # 10 (Robôs de transporte)
        self.metrology_queue = simpy.FilterStore(env, capacity=100)  # 11 (Inspeção com filtros)
        self.finished_goods = simpy.Store(env, capacity=1000)  # 12 (Armazém final)

        # Dynamic resource tracking.
        self.active_foups: Dict[str, simpy.Store] = {}  # 13+ (Recipientes criados sob demanda)
        self.dynamic_inspectors: Dict[str, simpy.Resource] = {}  # 14+ (Inspetores contratados sob demanda)

        # Background processes.
        self.env.process(self.facility_monitor())
        self.env.process(self.stepper_maintenance())
        self.env.process(self.dynamic_inspector_manager())

    def log(self, msg: str):
        logging.info(msg, extra={"sim_time": self.env.now})

    # Background routines.

    def facility_monitor(self):
        """Keep process-fluid containers replenished."""
        while True:
            if self.photoresist.level < 200:
                yield self.photoresist.put(800)
                self.log("Facility: Photoresist replenished.")
            if self.ultra_pure_water.level < 2000:
                yield self.ultra_pure_water.put(8000)
            yield self.env.timeout(10)

    def stepper_maintenance(self):
        """Trigger occasional stepper failures with preemptive maintenance."""
        while True:
            yield self.env.timeout(random.expovariate(1.0 / 60.0))
            if self.steppers.users:
                self.log("[FAILURE] Stepper broke down. Starting preemptive maintenance.")
                with self.steppers.request(priority=0, preempt=True) as maint_req:
                    yield maint_req
                    yield self.env.timeout(random.uniform(15, 45))
                    self.log("[FAILURE] Stepper repaired.")

    def dynamic_inspector_manager(self):
        """Create and remove inspectors dynamically based on queue pressure."""
        while True:
            queue_size = len(self.metrology_queue.items)
            active_dyn = len(self.dynamic_inspectors)

            # Scale out inspectors when metrology backlog grows.
            if queue_size > 10 and active_dyn < 3:
                res_id = f"DynInspector_{uuid.uuid4().hex[:6]}"
                self.dynamic_inspectors[res_id] = simpy.Resource(self.env, capacity=1)
                self.log(f"[SCALING] Metrology queue high ({queue_size}). Created dynamic resource: {res_id}")

            # Scale in idle dynamic inspectors when the queue is empty.
            elif queue_size == 0 and active_dyn > 0:
                to_remove = []
                for res_id, res in self.dynamic_inspectors.items():
                    if res.count == 0:
                        to_remove.append(res_id)

                for res_id in to_remove:
                    del self.dynamic_inspectors[res_id]
                    self.log(f"[SCALING] Decommissioning idle dynamic resource: {res_id}")

            yield self.env.timeout(20)


def process_lot(env: simpy.Environment, fab: SemiconductorFab, lot: Lot):
    """Lot lifecycle across transport, processing, inspection, and shipping."""
    fab.log(f"Lot {lot.id} started (Priority {lot.priority}).")

    # 1) Dynamic resource creation: FOUP (Front Opening Unified Pod).
    foup_id = f"FOUP_{lot.id}"
    fab.active_foups[foup_id] = simpy.Store(env, capacity=25)

    # Consume silicon, create wafers, and load them into the dynamic FOUP.
    yield fab.silicon_inventory.get(25)
    for i in range(25):
        wafer = Wafer(id=f"{lot.id}-W{i}")
        lot.wafers.append(wafer)
        yield fab.active_foups[foup_id].put(wafer)

    fab.log(f"Lot {lot.id} loaded into dynamic {foup_id}.")

    layers_target = 3
    for layer in range(layers_target):
        # 2) Combined event (AND): requires UPW, nitrogen, and AGV.
        req_upw = fab.ultra_pure_water.get(50)
        req_n2 = fab.nitrogen_gas.get(20)

        with fab.agv_fleet.request() as agv_req:
            yield req_upw & req_n2 & agv_req
            fab.log(f"Lot {lot.id} in safe transport for layer {layer+1}.")
            yield env.timeout(random.uniform(2, 5))

        # 3) Critical process with potential interruption (lithography).
        completed_litho = False
        while not completed_litho:
            try:
                yield fab.photoresist.get(10)
                # Priority-aware request: urgent lots can preempt normal flow.
                with fab.steppers.request(priority=lot.priority) as step_req:
                    yield step_req
                    fab.log(f"Lot {lot.id} in stepper.")
                    yield env.timeout(random.uniform(10, 20))
                    completed_litho = True
            except simpy.Interrupt:
                fab.log(f"Lot {lot.id} interrupted in stepper due to maintenance. Retrying layer.")

        # 4) Standard sequential processing.
        with fab.etchers.request() as etch_req:
            yield etch_req
            yield env.timeout(15)

        with fab.ion_implanters.request() as ion_req:
            yield ion_req
            yield env.timeout(25)

    # 5) Metrology and quality queue (FilterStore).
    yield fab.metrology_queue.put(lot)

    # Pull the same lot back from queue by ID after inspection.
    inspect_req = fab.metrology_queue.get(lambda l: l.id == lot.id)

    # 6) Optional dynamic inspector (OR): dynamic resource or timeout fallback.
    timeout_event = env.timeout(30)

    dynamic_req = None
    if fab.dynamic_inspectors:
        # Use any available dynamic inspector.
        inspector_id, dyn_res = random.choice(list(fab.dynamic_inspectors.items()))
        dynamic_req = dyn_res.request()

        results = yield dynamic_req | timeout_event

        if dynamic_req in results:
            fab.log(f"Lot {lot.id} inspected via dynamic resource {inspector_id}.")
            yield env.timeout(5)
            dyn_res.release(dynamic_req)
        else:
            dynamic_req.cancel()

    # Ensure the inspected lot leaves the FilterStore.
    inspected_lot = yield inspect_req

    # 7) Dynamic resource destruction and finalization.
    for _ in range(25):
        w = yield fab.active_foups[foup_id].get()
        yield fab.finished_goods.put(w)

    # Remove dynamic FOUP reference so it can be garbage-collected.
    del fab.active_foups[foup_id]

    lead_time = env.now - inspected_lot.creation_time
    fab.log(f"Lot {lot.id} FINISHED. FOUP removed. Lead time: {lead_time:.2f} min.")


def lot_generator(env: simpy.Environment, fab: SemiconductorFab):
    """Inject new production lots continuously."""
    lot_counter = 1
    while True:
        # Exponential inter-arrival of lots.
        yield env.timeout(random.expovariate(1.0 / 25.0))
        priority = 1 if random.random() > 0.1 else 2  # 10% of lots are high priority.

        new_lot = Lot(id=f"L{lot_counter:04d}", priority=priority, creation_time=env.now)
        env.process(process_lot(env, fab, new_lot))
        lot_counter += 1


# Example of a plain SimPy main (without GUI).
# if __name__ == "__main__":
#     random.seed(99)
#     env = simpy.Environment()
#     fab = SemiconductorFab(env)

#     env.process(lot_generator(env, fab))

#     logging.info("--- Starting Wafer Fab Simulation ---")
#     env.run(until=300)  # Run for 300 simulation minutes.

#     logging.info("--- Simulation Complete ---")
#     logging.info(f"Dynamic FOUPs still allocated: {len(fab.active_foups)}")
#     logging.info(f"Dynamic inspectors still allocated: {len(fab.dynamic_inspectors)}")
#     logging.info(f"Wafers in final warehouse: {len(fab.finished_goods.items)}")


# Example main to run with SimpyLens GUI.
def setup(env):
    fab = SemiconductorFab(env)
    env.process(lot_generator(env, fab))


if __name__ == "__main__":
    lens = simpylens.Lens(model=setup)
    lens.show()
