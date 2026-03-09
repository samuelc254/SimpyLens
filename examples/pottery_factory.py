"""
Pottery Factory example.

Covers:
- Resources: Resource
- Resources: Store
- Resources: Container
- Waiting for other processes

Scenario:
  A pottery factory produces different types of pots (Vases, Plates, Mugs).
  The production line consists of molding, glazing, oven firing (in batches),
  and final painting.

  The factory uses clay from a depot, which needs to be periodically refilled.
  Pots are finally shipped when finished.

  The resources are instantiated in the `setup` function to ensure
  they are registered by SimpyLens before the simulation starts.
"""

import random
import simpy
import simpylens

# LOG CONFIGURATION (True = show messages, False = silence)
VERBOSE = False

if not VERBOSE:

    def print(*args, **kwargs):
        pass


total_manufactured = 0


def factory(env, molding, glazing, painting, oven, clay_depot, shipping):
    """Main factory process that generates new pots to be processed."""
    env.process(clay_refill(env, clay_depot))

    pot_id = 1
    while True:
        arrival_time = max(0.5, random.normalvariate(2, 0.5))
        yield env.timeout(arrival_time)

        current_pot = {"id": pot_id, "type": random.choice(["Vase", "Plate", "Mug"]), "arrival": env.now}
        env.process(process_pot(env, current_pot, molding, glazing, oven, painting, clay_depot, shipping))
        pot_id += 1


def clay_refill(env, depot):
    """Independent process that periodically refills clay inventory."""
    while True:
        yield env.timeout(15)
        if depot.level < 50:
            yield depot.put(40)
            print(f"[{env.now:5.1f}] [System] Clay refill (+40). Stock: {depot.level}")


def process_pot(env, pot, molding, glazing, oven, painting, clay_depot, shipping):
    """Process a single pot through the manufacturing steps."""
    global total_manufactured
    pot_id = pot["id"]

    # --- STEP 1: MOLDING (consumes clay) ---
    yield clay_depot.get(2)
    with molding.request() as req:
        yield req
        mold_time = random.uniform(3, 5)
        yield env.timeout(mold_time)

    # --- STEP 2: GLAZING ---
    with glazing.request() as req:
        yield req
        yield env.timeout(2)

    # --- STEP 3: OVEN (batch) ---
    yield oven.put(pot)
    if len(oven.items) >= 5:
        print(f"[{env.now:5.1f}] [Oven] Starting batch firing with 5 items.")
        yield env.timeout(10)

        if hasattr(oven, "finished_firing"):
            oven.finished_firing.succeed()
            oven.finished_firing = env.event()

        ready_batch = []
        for _ in range(5):
            item = yield oven.get()
            ready_batch.append(item)

        if hasattr(oven, "batch_ready_event"):
            oven.batch_ready_event.succeed(value=ready_batch)
            oven.batch_ready_event = env.event()
    else:
        if not hasattr(oven, "batch_ready_event"):
            oven.batch_ready_event = env.event()
        if not hasattr(oven, "finished_firing"):
            oven.finished_firing = env.event()

        yield oven.finished_firing
        yield oven.batch_ready_event

    # --- STEP 4: FINAL PAINTING ---
    with painting.request() as req:
        yield req
        yield env.timeout(2)

    # --- STEP 5: SHIPPING ---
    yield shipping.put(1)

    total_manufactured += 1
    print(f"[{env.now:5.1f}] [Pot {pot_id}] COMPLETED and stocked. (Total: {total_manufactured})")


def setup(env):
    """Setup function for SimpyLens. Instantiates resources and starts the factory."""
    # --- RESOURCES (MACHINES AND OPERATORS) ---
    molding = simpy.Resource(env, capacity=3)
    glazing = simpy.Resource(env, capacity=2)
    painting = simpy.Resource(env, capacity=2)

    # --- STORE (BATCH PROCESS) ---
    oven = simpy.Store(env, capacity=5)

    # --- CONTAINERS (BULK INVENTORY) ---
    clay_depot = simpy.Container(env, capacity=100, init=20)
    shipping = simpy.Container(env, capacity=1000, init=0)

    # Naming resources for better visualization in SimpyLens
    molding.visual_name = "Molding Station"
    glazing.visual_name = "Glazing Station"
    painting.visual_name = "Painting Station"
    oven.visual_name = "Oven"
    clay_depot.visual_name = "Clay Depot"
    shipping.visual_name = "Shipping Depot"

    # Start the factory process
    env.process(factory(env, molding, glazing, painting, oven, clay_depot, shipping))


lens = simpylens.Lens(model=setup, title="Pottery Factory Simulation")
lens.add_breakpoint("len(resources['Oven'].items) >= 5", label="Oven Batch Ready", edge="rising", pause_on_hit=False)
lens.add_breakpoint("resources['Shipping Depot'].level >= 50", edge="rising")
lens.add_breakpoint("env.now >= 500", edge="rising")
lens.add_breakpoint("any(item['type'] == 'Mug' for item in resources['Oven'].items)", label="Mug in Oven", edge="rising", pause_on_hit=False)
lens.add_breakpoint("env.step_count >= 50", label="Step Count Reached", edge="rising")

lens.show()