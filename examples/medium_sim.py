import simpy
import simpylens
import random

# LOG CONFIGURATION
VERBOSE = False

if not VERBOSE:

    def print(*args, **kwargs):
        pass


patients_served = 0


def hospital_run(env):
    global patients_served

    reception = simpy.Resource(env, capacity=3)
    triage = simpy.Resource(env, capacity=2)
    waiting_room = simpy.Store(env, capacity=50)
    consultation_rooms = simpy.Resource(env, capacity=5)
    laboratory = simpy.Resource(env, capacity=2)
    blood_bank = simpy.Container(env, capacity=100, init=80)
    pharmacy = simpy.Container(env, capacity=500, init=400)
    surgery_center = simpy.Resource(env, capacity=1)
    recovery_room = simpy.Store(env, capacity=5)
    billing = simpy.Resource(env, capacity=2)

    env.process(logistics_resupply(env, blood_bank, pharmacy))

    patient_id = 1
    while True:
        yield env.timeout(random.expovariate(1.0 / 2.0))
        patient_type = random.choice(["Normal", "Normal", "Normal", "Urgent"])
        patient = {"id": patient_id, "type": patient_type, "arrival": env.now}

        env.process(
            patient_process(
                env,
                patient,
                reception,
                triage,
                waiting_room,
                consultation_rooms,
                laboratory,
                blood_bank,
                pharmacy,
                surgery_center,
                recovery_room,
                billing,
            )
        )
        patient_id += 1


def logistics_resupply(env, blood, meds):
    """Supply truck arrives periodically."""
    while True:
        yield env.timeout(100)
        missing_blood = blood.capacity - blood.level
        if missing_blood > 10:
            yield blood.put(min(20, missing_blood))
            print("[Logistics] Blood refilled.")

        yield meds.put(50)
        print("[Logistics] Pharmacy refilled.")


def patient_process(env, patient, reception, triage, waiting_room, consultation, lab, blood, pharmacy, surgery, recovery, billing):
    global patients_served
    patient_id = patient["id"]
    patient_type = patient["type"]

    print(f"Patient {patient_id} ({patient_type}) arrived.")

    with reception.request() as req:
        yield req
        yield env.timeout(random.uniform(1, 3))

    with triage.request() as req:
        yield req
        yield env.timeout(random.uniform(2, 5))

    yield waiting_room.put(f"P{patient_id}")

    doctor_request = consultation.request()
    yield doctor_request

    yield waiting_room.get()

    consultation_time = random.uniform(5, 15)
    yield env.timeout(consultation_time)

    chance = random.random()

    if chance < 0.2:
        consultation.release(doctor_request)
        print(f"Patient {patient_id} sent to SURGERY.")

        if blood.level >= 2:
            yield blood.get(2)

        with surgery.request() as surgery_request:
            yield surgery_request
            yield env.timeout(random.uniform(20, 40))

        yield recovery.put(f"P{patient_id}-Recovery")
        yield env.timeout(15)
        yield recovery.get()

    elif chance < 0.5:
        consultation.release(doctor_request)

        with lab.request() as lab_request:
            yield lab_request
            yield env.timeout(random.uniform(5, 10))

        yield pharmacy.get(1)

    else:
        consultation.release(doctor_request)
        yield env.timeout(1)

    yield pharmacy.get(random.randint(1, 3))

    with billing.request() as req:
        yield req
        yield env.timeout(random.uniform(2, 4))

    patients_served += 1
    print(f"Patient {patient_id} discharged.")


def setup(env):
    env.process(hospital_run(env))


if __name__ == "__main__":
    import simpylens

    sim_view = simpylens.Viewer(model=setup)
    sim_view.mainloop()
