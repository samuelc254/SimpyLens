# monkey_patch.py
import simpy
import inspect
import re

# Lista global para armazenar os recursos interceptados
recursos_rastreados = []

# Lista de transferências para animação: [{'from': obj_origem, 'to': obj_destino, 'item': process_ref}]
transferencias_pendentes = []

# Mapa para rastrear onde cada Processo (via hash/id) estava por último
# Chave: active_process, Valor: resource_instance
process_last_location = {}


def registrar_interacao(env, resource_instance):
    """
    Função auxiliar chamada pelos métodos interceptados para registrar o fluxo.
    """
    if not env or not hasattr(env, "active_process") or env.active_process is None:
        return

    proc = env.active_process

    # Se ja sabemos onde ele estava
    if proc in process_last_location:
        last_loc = process_last_location[proc]

        # Se mudou de lugar (e não é o mesmo recurso)
        if last_loc != resource_instance:
            transferencias_pendentes.append({"from": last_loc, "to": resource_instance, "item": str(proc)})  # Salva string para não segurar referencia forte se não precisar

    # Atualiza localização atual
    process_last_location[proc] = resource_instance


def tentar_descobrir_nome():
    """
    Tenta descobrir o nome da variável que está recebendo a instância.
    Analisa a stack de chamadas para encontrar a linha de código 'variavel = Classe(...)'.
    """
    try:
        # Pega o frame anterior (quem chamou o __init__)
        frame = inspect.currentframe().f_back.f_back

        # Pega o código fonte e o número da linha
        arquivo = inspect.getsourcefile(frame)
        if not arquivo:
            return None

        linhas, linha_inicial = inspect.getsourcelines(frame)
        linha_atual = frame.f_lineno - linha_inicial

        # O código pode estar em múltiplas linhas, mas vamos simplificar pegando a linha da chamada
        # Às vezes inspect aponta para a linha exata, às vezes para o inicio da função,
        # então pegamos o contexto do arquivo via 'code_context' do frame info
        info = inspect.getframeinfo(frame)
        if not info.code_context:
            return None

        codigo = "".join(info.code_context).strip()

        # Procura por padrão: nome_variavel = ...
        # Regex captura tudo antes do sinal de igual
        match = re.search(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=", codigo)
        if match:
            return match.group(1)

    except Exception:
        pass

    return None


# Guardamos as classes originais para poder chamar o super().__init__
OriginalResource = simpy.Resource
OriginalContainer = simpy.Container
OriginalStore = simpy.Store


class TrackedResource(OriginalResource):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        idx = len(recursos_rastreados) + 1

        nome_var = tentar_descobrir_nome()
        if nome_var:
            self.nome_visual = nome_var  # Usa o nome da variável!
        else:
            self.nome_visual = f"Recurso_{idx} (Resource)"

        self.tipo_visual = "RESOURCE"
        recursos_rastreados.append(self)

    def request(self, *args, **kwargs):
        # Intercepta o request
        registrar_interacao(self._env, self)
        return super().request(*args, **kwargs)


class TrackedContainer(OriginalContainer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        idx = len(recursos_rastreados) + 1

        nome_var = tentar_descobrir_nome()
        if nome_var:
            self.nome_visual = nome_var
        else:
            self.nome_visual = f"Recurso_{idx} (Container)"

        self.tipo_visual = "CONTAINER"
        recursos_rastreados.append(self)

    def put(self, *args, **kwargs):
        registrar_interacao(self._env, self)
        return super().put(*args, **kwargs)

    def get(self, *args, **kwargs):
        registrar_interacao(self._env, self)
        return super().get(*args, **kwargs)


class TrackedStore(OriginalStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        idx = len(recursos_rastreados) + 1

        nome_var = tentar_descobrir_nome()
        if nome_var:
            self.nome_visual = nome_var
        else:
            self.nome_visual = f"Recurso_{idx} (Store)"

        self.tipo_visual = "STORE"
        self.is_expanded = False  # Estado de expansão para a GUI
        recursos_rastreados.append(self)

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
