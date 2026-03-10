"""Bank Renege Example.

Origin:
    Adapted from the official SimPy examples/tutorial material.

Credits:
    - SimPy documentation and examples: https://simpy.readthedocs.io/
    - Original "bank08.py" concept from TheBank tutorial lineage.

Covers:
    - Resource usage (`simpy.Resource`)
    - Condition events (`req | env.timeout(...)`)
    - Log export with SimpyLens

Scenario:
    A single service counter with random service times and customers that may
    renege if waiting longer than their patience threshold.
"""

import json
import random

import simpy
import simpylens

RANDOM_SEED = 42
NEW_CUSTOMERS = 5  # Total number of customers
INTERVAL_CUSTOMERS = 10.0  # Generate new customers roughly every x seconds
MIN_PATIENCE = 1  # Min. customer patience
MAX_PATIENCE = 3  # Max. customer patience


def source(env, number, interval, counter):
    """Source generates customers randomly"""
    for i in range(number):
        c = customer(env, f"Customer{i:02d}", counter, time_in_bank=12.0)
        env.process(c)
        t = random.expovariate(1.0 / interval)
        yield env.timeout(t)


def customer(env, name, counter, time_in_bank):
    """Customer arrives, is served and leaves."""
    arrive = env.now
    print(f"{arrive:7.4f} {name}: Here I am")

    with counter.request() as req:
        patience = random.uniform(MIN_PATIENCE, MAX_PATIENCE)
        # Wait for the counter or abort at the end of our tether
        results = yield req | env.timeout(patience)

        wait = env.now - arrive

        if req in results:
            # We got to the counter
            print(f"{env.now:7.4f} {name}: Waited {wait:6.3f}")

            tib = random.expovariate(1.0 / time_in_bank)
            yield env.timeout(tib)
            print(f"{env.now:7.4f} {name}: Finished")

        else:
            # We reneged
            print(f"{env.now:7.4f} {name}: RENEGED after {wait:6.3f}")


def setup(env):
    """Setup function for SimpyLens. Instantiates resources and starts the simulation."""
    counter = simpy.Resource(env, capacity=1)
    env.process(source(env, NEW_CUSTOMERS, INTERVAL_CUSTOMERS, counter))


# Run the simulation headlessly and export event logs.
lens = simpylens.Lens(model=setup, seed=RANDOM_SEED, gui=False)
lens.run()

logs = lens.get_logs()
with open("bank_renege_logs.json", "w") as log_file:
    json.dump(logs, log_file, indent=4)
