# monkey_patch.py
import simpy
import inspect
import re
import weakref

# Usamos WeakSet para não impedir que o GC colete objetos destruídos
recursos_rastreados = weakref.WeakSet()
# Mantemos uma lista auxiliar para iterar de forma ordenada se necessario, ou apenas usamos o set
# Como WeakSet não é iterável consistentemente durante GC, pode ser truque
# Mas vamos assumir iteração segura na GUI copiando o set

# Lista de transferências para animação (eventos transientes)
transferencias_pendentes = []

# Mapa para rastrear onde cada Processo (via hash/id) estava por último
# Chave: active_process (weakref), Valor: resource_instance (obj)
# Precisamos de um dicionário que não segure o processo
process_locations = weakref.WeakKeyDictionary()


def registrar_interacao(env, resource_instance):
    """
    Função auxiliar chamada pelos métodos interceptados para registrar o fluxo.
    """
    if not env or not hasattr(env, "active_process") or env.active_process is None:
        return

    proc = env.active_process

    # Se ja sabemos onde ele estava
    if proc in process_locations:
        last_loc = process_locations[proc]

        # Se mudou de lugar (e não é o mesmo recurso)
        if last_loc != resource_instance:
            transferencias_pendentes.append({"from": last_loc, "to": resource_instance, "item": str(proc)})

    # Atualiza localização atual
    process_locations[proc] = resource_instance


def tentar_descobrir_nome(instance):
    """Tenta descobrir o nome da variável que está recebendo a instância."""
    try:
        # Pega o frame anterior (quem chamou o __init__)
        frame = inspect.currentframe().f_back.f_back
        if not frame:
            return None

        # Pega o código fonte e o número da linha
        arquivo = inspect.getsourcefile(frame)
        if not arquivo:
            return None

        # info = inspect.getframeinfo(frame)
        # if not info.code_context: return None
        # codigo = "".join(info.code_context).strip()

        # Usando getsourcelines + lineno para robustez
        lines, start = inspect.getsourcelines(frame)
        relative_line = frame.f_lineno - start
        if 0 <= relative_line < len(lines):
            codigo = lines[relative_line].strip()
            match = re.search(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=", codigo)
            if match:
                return match.group(1)

    except Exception:
        pass
    return None


# Guardamos as classes originais
OriginalResource = simpy.Resource
OriginalContainer = simpy.Container
OriginalStore = simpy.Store


class TrackedResource(OriginalResource):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.nome_visual = tentar_descobrir_nome(self) or f"Resource_{id(self)}"
        self.tipo_visual = "RESOURCE"
        recursos_rastreados.add(self)

    def request(self, *args, **kwargs):
        registrar_interacao(self._env, self)
        return super().request(*args, **kwargs)


class TrackedContainer(OriginalContainer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.nome_visual = tentar_descobrir_nome(self) or f"Container_{id(self)}"
        self.tipo_visual = "CONTAINER"
        recursos_rastreados.add(self)

    def put(self, *args, **kwargs):
        registrar_interacao(self._env, self)
        return super().put(*args, **kwargs)

    def get(self, *args, **kwargs):
        registrar_interacao(self._env, self)
        return super().get(*args, **kwargs)


class TrackedStore(OriginalStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.nome_visual = tentar_descobrir_nome(self) or f"Store_{id(self)}"
        self.tipo_visual = "STORE"
        self.is_expanded = False
        recursos_rastreados.add(self)

    def put(self, *args, **kwargs):
        registrar_interacao(self._env, self)
        return super().put(*args, **kwargs)

    def get(self, *args, **kwargs):
        registrar_interacao(self._env, self)
        return super().get(*args, **kwargs)


def apply_patch():
    """Aplica o Monkey Patch nas classes do SimPy."""
    simpy.Resource = TrackedResource
    simpy.Container = TrackedContainer
    simpy.Store = TrackedStore
