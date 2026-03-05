import simpy
import simpylens
import random

# LOG CONFIGURATION (True = show messages, False = silence)
VERBOSE = False

if not VERBOSE:

    def print(*args, **kwargs):
        pass


total_manufactured = 0


def factory(env):
    global total_manufactured

    # --- RESOURCES (MACHINES AND OPERATORS) ---
    molding = simpy.Resource(env, capacity=3)
    glazing = simpy.Resource(env, capacity=2)
    painting = simpy.Resource(env, capacity=2)

    # --- STORE (BATCH PROCESS) ---
    oven = simpy.Store(env, capacity=5)

    # --- CONTAINERS (BULK INVENTORY) ---
    clay_depot = simpy.Container(env, capacity=100, init=20)
    shipping = simpy.Container(env, capacity=1000, init=0)

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
            print(f"[System] Clay refill (+40). Stock: {depot.level}")


def process_pot(env, pot, molding, glazing, oven, painting, clay_depot, shipping):
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
        print("[Oven] Starting batch firing with 5 items.")

        for item in oven.items:
            print(f"  - Item {item['id']} ({item['type']}) in batch.")

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
    print(f"[Pot {pot_id}] COMPLETED and stocked. (Total: {total_manufactured})")


def setup(env):
    env.process(factory(env))


if __name__ == "__main__":
    lens = simpylens.Lens(model=setup)

    lens.add_breakpoint("len(oven.items) >= 5", label="Oven Batch Ready", edge="rising")
    lens.add_breakpoint("shipping.level >= 10", edge="rising")
    lens.add_breakpoint("env.now >= 50", edge="rising")
    lens.add_breakpoint("any(item['type'] == 'Mug' for item in oven.items)", label="Mug in Oven", edge="rising")
    # lens.add_breakpoint("a==b")

    lens.show()