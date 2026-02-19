# monkey_patch.py
import simpy

# Lista global para armazenar os recursos interceptados
recursos_rastreados = []

# Guardamos as classes originais para poder chamar o super().__init__
OriginalResource = simpy.Resource
OriginalContainer = simpy.Container
OriginalStore = simpy.Store


class TrackedResource(OriginalResource):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        idx = len(recursos_rastreados) + 1
        self.nome_visual = f"Recurso_{idx} (Resource)"
        self.tipo_visual = "RESOURCE"
        recursos_rastreados.append(self)


class TrackedContainer(OriginalContainer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        idx = len(recursos_rastreados) + 1
        self.nome_visual = f"Recurso_{idx} (Container)"
        self.tipo_visual = "CONTAINER"
        recursos_rastreados.append(self)


class TrackedStore(OriginalStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        idx = len(recursos_rastreados) + 1
        self.nome_visual = f"Recurso_{idx} (Store)"
        self.tipo_visual = "STORE"
        recursos_rastreados.append(self)


def apply_patch():
    """Aplica o Monkey Patch nas classes do SimPy."""
    simpy.Resource = TrackedResource
    simpy.Container = TrackedContainer
    simpy.Store = TrackedStore
