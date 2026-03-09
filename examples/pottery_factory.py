"""Pottery Factory Example.

Origin:
    Original SimpyLens example.

Credits:
    - SimpyLens maintainers.

Covers:
    - Resource usage (`simpy.Resource`)
    - Store usage (`simpy.Store`) with batch firing logic
    - Container usage (`simpy.Container`) for bulk inventory
    - Runtime breakpoints in SimpyLens

Scenario:
    A pottery factory produces vases, plates, and mugs. Items go through molding,
    glazing, oven firing in batches, painting, and shipping. Clay inventory is
    periodically refilled to keep production running.
"""

import random
import simpy
import simpylens

# Log configuration (True = show messages, False = silence).
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

    # Step 1: molding (consumes clay).
    yield clay_depot.get(2)
    with molding.request() as req:
        yield req
        mold_time = random.uniform(3, 5)
        yield env.timeout(mold_time)

    # Step 2: glazing.
    with glazing.request() as req:
        yield req
        yield env.timeout(2)

    # Step 3: oven firing (batch).
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

    # Step 4: final painting.
    with painting.request() as req:
        yield req
        yield env.timeout(2)

    # Step 5: shipping.
    yield shipping.put(1)

    total_manufactured += 1
    print(f"[{env.now:5.1f}] [Pot {pot_id}] COMPLETED and stocked. (Total: {total_manufactured})")


def setup(env):
    """Setup function for SimpyLens. Instantiates resources and starts the factory."""
    # Resources: machines and operators.
    molding = simpy.Resource(env, capacity=3)
    glazing = simpy.Resource(env, capacity=2)
    painting = simpy.Resource(env, capacity=2)

    # Store for the oven batch process.
    oven = simpy.Store(env, capacity=5)

    # Containers for bulk inventory.
    clay_depot = simpy.Container(env, capacity=100, init=20)
    shipping = simpy.Container(env, capacity=1000, init=0)

    # Resource labels for clearer SimpyLens visualization.
    molding.visual_name = "Molding Station"
    glazing.visual_name = "Glazing Station"
    painting.visual_name = "Painting Station"
    oven.visual_name = "Oven"
    clay_depot.visual_name = "Clay Depot"
    shipping.visual_name = "Shipping Depot"

    # Start the factory process.
    env.process(factory(env, molding, glazing, painting, oven, clay_depot, shipping))


lens = simpylens.Lens(model=setup, title="Pottery Factory Simulation")

lens.add_breakpoint("any(item['type'] == 'Mug' for item in resources['Oven'].items)", label="Mug in Oven", edge="none", pause_on_hit=False)
lens.add_breakpoint("len(resources['Oven'].items) >= 5", label="Oven Batch Ready", edge="rising", pause_on_hit=False)
lens.add_breakpoint("resources['Shipping Depot'].level >= 50", label="Shipping Depot Full", edge="rising", pause_on_hit=False)
lens.add_breakpoint("env.step_count >= 1000", label="Step Count Reached", edge="rising")
lens.add_breakpoint("env.now >= 200", label="Time Limit Reached", edge="rising")

lens.show()
