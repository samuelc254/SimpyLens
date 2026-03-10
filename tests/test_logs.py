import pytest
import simpy
from simpylens import Lens

def long_model(env):
    def process_a(env):
        for i in range(2000):
            yield env.timeout(1)
            env.step_logs.append({"msg": f"Event {i}", "val": i})
            
    env.process(process_a(env))

def test_log_capacity():
    lens = Lens(model=long_model, gui=False)
    
    # Verify default capacity is 1000
    lens.run()
    logs = lens.get_logs()
    
    assert len(logs) <= 1000
    
    # The last logs should contain our custom log.
    found = any("Event 1999" in str(log) for log in logs[-20:])
    assert found

def test_set_log_capacity():
    lens = Lens(model=long_model, gui=False)
    lens.set_log_capacity(50)
    
    lens.run()
    logs = lens.get_logs()
    
    # First few events include RESET, etc. But the total buffer size is 50
    assert len(logs) == 50
    
    lens.set_log_capacity(100)
    # The buffer should now hold 100, currently has 50.
    logs_after_increase = lens.get_logs()
    assert len(logs_after_increase) == 50
    
    # If we reset and run again, buffer gets new logs
    lens.reset()
    lens.run()
    logs_new = lens.get_logs()
    assert len(logs_new) == 100
