"""
Gas Station Refueling example.

Original Credit: SimPy Examples (https://simpy.readthedocs.io/en/latest/examples/gas_station_refuel.html)
Adapted for SimpyLens to demonstrate visualization and breakpoints.

Covers:
- Resources: Resource
- Resources: Container
- Waiting for other processes

Scenario:
  A gas station has a limited number of gas pumps that share a common
  fuel reservoir. Cars randomly arrive at the gas station, request one
  of the fuel pumps and start refueling from that reservoir.

  A gas station control process observes the gas station's fuel level
  and calls a tank truck for refueling if the station's level drops
  below a threshold.
"""

import itertools
import random

import simpy
import simpylens

# fmt: off
RANDOM_SEED = 42
STATION_TANK_SIZE = 200    # Size of the gas station tank (liters)
THRESHOLD = 25             # Station tank minimum level (% of full)
CAR_TANK_SIZE = 50         # Size of car fuel tanks (liters)
CAR_TANK_LEVEL = [5, 25]   # Min/max levels of car fuel tanks (liters)
REFUELING_SPEED = 2        # Rate of refuelling car fuel tank (liters / second)
TANK_TRUCK_TIME = 300      # Time it takes tank truck to arrive (seconds)
T_INTER = [30, 300]        # Interval between car arrivals [min, max] (seconds)
SIM_TIME = 1000            # Simulation time (seconds)
# fmt: on


def car(name, env, gas_station, station_tank):
    """A car arrives at the gas station for refueling.

    It requests one of the gas station's fuel pumps and tries to get the
    desired amount of fuel from it. If the station's fuel tank is
    depleted, the car has to wait for the tank truck to arrive.
    """
    car_tank_level = random.randint(*CAR_TANK_LEVEL)
    print(f"{env.now:6.1f} s: {name} arrived at gas station")
    with gas_station.request() as req:
        # Request one of the gas pumps
        yield req

        # Get the required amount of fuel
        fuel_required = CAR_TANK_SIZE - car_tank_level
        yield station_tank.get(fuel_required)

        # The "actual" refueling process takes some time
        yield env.timeout(fuel_required / REFUELING_SPEED)

        print(f"{env.now:6.1f} s: {name} refueled with {fuel_required:.1f}L")


def gas_station_control(env, station_tank):
    """Periodically check the level of the gas station tank and call the tank
    truck if the level falls below a threshold."""
    while True:
        if station_tank.level / station_tank.capacity * 100 < THRESHOLD:
            # We need to call the tank truck now!
            print(f"{env.now:6.1f} s: Calling tank truck")
            # Wait for the tank truck to arrive and refuel the station tank
            yield env.process(tank_truck(env, station_tank))

        yield env.timeout(10)  # Check every 10 seconds


def tank_truck(env, station_tank):
    """Arrives at the gas station after a certain delay and refuels it."""
    yield env.timeout(TANK_TRUCK_TIME)
    amount = station_tank.capacity - station_tank.level
    station_tank.put(amount)
    print(f"{env.now:6.1f} s: Tank truck arrived and refuelled station with {amount:.1f}L")


def car_generator(env, gas_station, station_tank):
    """Generate new cars that arrive at the gas station."""
    for i in itertools.count():
        yield env.timeout(random.randint(*T_INTER))
        env.process(car(f"Car {i}", env, gas_station, station_tank))


def setup(env):
    """Setup function for SimpyLens. Instantiates resources and starts the generator."""
    gas_station = simpy.Resource(env, 2)
    station_tank = simpy.Container(env, STATION_TANK_SIZE, init=STATION_TANK_SIZE)

    # Naming resources for better visualization in SimpyLens
    gas_station.visual_name = "Gas Pumps"
    station_tank.visual_name = "Station Tank"

    env.process(gas_station_control(env, station_tank))
    env.process(car_generator(env, gas_station, station_tank))


if __name__ == "__main__":
    lens = simpylens.Lens(model=setup, seed=RANDOM_SEED, title="Gas Station Refueling")

    # Add a breakpoint to pause simulation when the tank truck arrives
    # Expression evaluates if a breakpoint condition is met based on the logs
    lens.add_breakpoint("env.last_event_name == 'Initialize' and env.last_process_name == 'tank_truck'", label="Tank truck on the way")

    lens.show()
