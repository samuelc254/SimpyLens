# TODO v1 — SimpyLens

## Backlog funcional

- adicionar modo headless para rodar a simulação sem interface gráfica, apenas com breakpoints programáticos e logs
- corrigir gif do readme para rodar em loop (passo futuro)
- adicionar testes unitários (passo futuro)
- adicionar rewind step (avaliar a viabilidade) (passo futuro)
- deixar tamanho do log salvo configurável e adicionar opção de salvar o log em um arquivo
- adicionar teste de alterar breakpoints com a simulação rodando (passo futuro)
- adicionar mais metricas de fila, media de itens na fila, min e max (fila de put get e fila de request)


---

## Arquitetura alvo

- patch de métricas: renomear para `simpylens.MetricsPatch.apply()` para não confundir com patch do viewer
    - independente de `simpylens.Lens`
    - usável sem viewer e sem breakpoints
    - aplicação idempotente
- patch de tracking para viewer/log: renomear para `simpylens.TrackingPatch.apply()`
    - independente de `simpylens.Lens`
    - usável sem viewer e sem breakpoints
    - aplicação idempotente
- núcleo da biblioteca: `simpylens.Lens`
    - classe principal que gerencia facilidades prontas: breakpoints, logs e viewer
    - deve rodar opcionalmente sem viewer (headless)
    - métricas e tracking continuam independentes
    - seed reproduzível via `lens.seed`
    - breakpoints via `lens.add_breakpoint()`
    - viewer via `lens.viewer.mainloop()` quando `gui=True`

---

## API pública mínima (v1)

Objetivo: definir o contrato oficial para a v1 e evitar mudanças quebrando integração de usuários.

### 1) Classe `Lens` (entrada principal)

Construtor:
- `Lens(model=None, title="SimPyLens", gui=True , metrics=True, seed=42)` (se metrics true aplica `MetricsPatch` automaticamente; se false, não aplica e não coleta métricas)

Contrato do parâmetro `model`:
- `model` deve ser uma função/callable que recebe exatamente o ambiente de simulação (um objeto `simpy.Environment`)
como primeiro argumento.
- assinatura esperada: `def model(env: simpy.Environment): ...`

Métodos oficiais:
- `set_model(model)`
- `set_seed(seed)`
- `run()` (sem GUI roda normalmente com breakpoints e logs; com GUI equivale a `show()` e depois play, portanto é bloqueante tanto quando `gui=True` como quando `gui=False`)
- `step()` (independente do GUI, avança em um passo; com GUI equivale ao botão de step)
- `reset()` (recria ambiente e reaplica seed; com GUI equivale ao botão de reset)
- `add_breakpoint(condition, label=None, enabled=True, pause_on_hit=True, edge="none")` ou `add_breakpoint(breakpoint)`
- `remove_breakpoint(breakpoint_id)`
- `clear_breakpoints()`
- `set_breakpoint_enabled(breakpoint_id, enabled)`
- `set_breakpoint_pause_on_hit(breakpoint_id, pause_on_hit)`
- `list_breakpoints()` (retorna cópia da lista atual com todos os objetos de breakpoint)
- `show()` (inicia GUI de forma bloqueante (mainloop do Tkinter)); sem GUI retorna valor seguro)
- `get_logs()` (retorna JSON com raiz em lista)
- `set_log_capacity(capacity)` (capacidade máxima do log; padrão 1000)

Objetos de breakpoint:
- `simpylens.Breakpoint` (classe ou objeto compatível para `add_breakpoint()`)
- atributos públicos:
    - `id` (único, gerado automaticamente, imutável)
    - `condition` (string, ex: `"env.now > 10 and len(env.queue) > 0"`)
    - `label` (string, opcional, para identificação amigável)
    - `enabled` (bool)
    - `pause_on_hit` (bool)
    - `edge` (`"none"`, `"rising"`, `"falling"`)

Atributos públicos esperados:
- `lens.model` (somente leitura, escrita via `set_model()`)
- `lens.seed` (somente leitura, escrita via `set_seed()`)
- `lens.title` (somente leitura, definido no construtor)
- `lens.gui` (somente leitura, definido no construtor)

Regras de comportamento v1:
- `reset()` sempre recria o ambiente e reaplica `seed`
- `run()` e `show()` sem `model` definido não devem quebrar (retorno seguro)
- breakpoints funcionam com ou sem UI (dependem de `Lens`)
- quando `gui=True`, `Lens` cria e gerencia o ciclo de vida do viewer
- `Viewer` não faz parte da API pública 

---

### 2) Componente interno `Viewer` (não público)

Diretriz de arquitetura:
- `Viewer` é interno da biblioteca e não deve ser usado como ponto de entrada pelo usuário final
- somente `Lens` pode criar e gerenciar o `Viewer`

Objetivo do componente:
- visualizar e inspecionar a simulação
- não alterar regras de negócio do modelo do usuário

Contrato de produto:
- não exportar `Viewer` como API oficial da v1
- exemplos e documentação devem usar apenas `Lens` como entrada

---

### 3) Patch de tracking (independente)

Classe pública proposta:
- `simpylens.TrackingPatch.apply()`

Escopo:
- coleta de dados de tracking para visualização/log
- uso independente de `Lens`, e `MetricsPatch`

Contrato mínimo:
- aplicação idempotente (chamar duas vezes não deve quebrar)
- não exigir UI para funcionar
- usar em conjunto com `MetricsPatch` deve ser possível, mas não obrigatório

---

### 4) Patch de métricas (independente)

Classe pública proposta:
- `simpylens.MetricsPatch.apply()`

Escopo:
- coleta de métricas (contadores, tempos, throughput, etc)
- uso independente de `Lens`, `TrackingPatch` e breakpoints

Contrato mínimo:
- aplicação idempotente
- API de leitura/export de métricas definida e estável na v1
- usar em conjunto com `TrackingPatch` deve ser possível, mas não obrigatório

- `<Resource/Store/Container>` deve ter um atributo público `metrics` com as métricas atuais, atualizadas em tempo real, e expostas de forma consistente (ex: `my_resource.metrics.example_metric`)

- `Resource` deve ter métricas publicas de: (todos somente leitura, sem setters públicos)
    - tempo mínimo, médio e máximo de espera na fila (tempo entre `request` e obtenção do recurso)
    - tempo mínimo, médio e máximo de uso do recurso (tempo entre `request` e `release` do mesmo processo)
    - contagem total de aquisições do recurso e liberações
    - porcentagem de de tempo total que o recurso ficou ocioso (sem processos usando) vs ocupado (pelo menos um processo usando)
    - mínima, média e máxima quantidade de quantidade de processos sendo atendidos simultaneamente ao longo da simulação (para recursos com `capacity > 1`)

- `Store` deve ter métricas públicas de: (todos somente leitura, sem setters públicos)
    - tempo mínimo, médio e máximo de espera para retirada de item (tempo entre `get` e obtenção do item)
    - tempo mínimo, médio e máximo de espera para depósito de item (tempo entre `put` e aceitação do item)
    - contagem total de itens depositados
    - contagem total de itens retirados
    - nível mínimo, médio e máximo da store ao longo do tempo (para avaliar se está frequentemente cheia, vazia ou em um nível intermediário)

- `Container` deve ter métricas públicas de: (todos somente leitura, sem setters públicos)
    - tempo mínimo, médio e máximo de espera para retirada de quantidade por unidade (tempo entre `get` e obtenção da quantidade divida pela quantidade solicitada)
    - tempo mínimo, médio e máximo de espera para depósito de quantidade por unidade (tempo entre `put` e aceitação da quantidade divida pela quantidade solicitada)
    - contagem total de quantidade depositada
    - contagem total de quantidade retirada
    - nível mínimo, médio e máximo do container ao longo do tempo (para avaliar se está frequentemente cheio, vazio ou em um nível intermediário)

---

### 5) Convenções gerais da API v1

- nome oficial para função de entrada do usuário: `model`
- não usar aliases legados na API pública v1
- métodos públicos devem ter docstring com exemplo curto
- alterações breaking só em v2+

---

### 6) Contrato de logs (interno eficiente + saída JSON)

Objetivo:
- internamente, logs devem ser tratados com estrutura eficiente para escrita frequente (append O(1), capacidade limitada e descarte dos mais antigos)
- externamente, logs devem sempre sair como JSON estável via `lens.get_logs()`

Estrutura interna esperada (não pública):
- buffer circular/fila limitada (`log_capacity`, padrão 1000)
- itens podem ser armazenados internamente como dicts Python ou estrutura equivalente otimizada
- serialização para JSON deve acontecer somente no boundary público (`get_logs()`/export)

Formato público obrigatório (`get_logs()`):
- retorno deve ser uma lista JSON, onde cada item é um objeto de log
- cada objeto deve conter no mínimo:
        - `schema_version` (string, ex: `"1.0"`)
        - `seq` (inteiro crescente, único por execução)
        - `kind` (string de categoria alta, ex: `"STATUS"`, `"SIM"`, `"RESOURCE"`, `"BREAKPOINT"`, `"ERROR"`)
        - `event` (string curta e estável, ex: `"RESET"`, `"STEP"`, `"BREAKPOINT_HIT"`)
        - `time` (tempo da simulação, numérico)
- campos recomendados:
        - `level` (`"DEBUG"`, `"INFO"`, `"WARN"`, `"ERROR"`)
        - `source` (origem do evento, ex: `"lens"`, `"tracking"`, `"metrics"`, `"viewer"`)
        - `message` (resumo legível para humano)
        - `data` (objeto JSON com payload específico do evento)

Padrões de nomenclatura e compatibilidade:
- nomes de chaves em `snake_case`
- `kind` e `event` em maiúsculas com `_` (ex: `BREAKPOINT_ERROR`)
- eventos já existentes devem manter nomenclatura estável para não quebrar integrações
- novos campos só podem ser adicionados de forma backward-compatible (sem remover/renomear campos obrigatórios na v1)

Regras de comportamento:
- `lens.set_log_capacity(capacity)` altera o tamanho máximo do buffer; ao exceder, descarta do mais antigo para o mais novo
- `lens.get_logs()` sempre retorna snapshot serializável em JSON, sem expor referências internas mutáveis
- logs devem funcionar com e sem GUI
- erro de avaliação de breakpoint deve gerar evento `BREAKPOINT_ERROR`
- disparo de breakpoint deve gerar evento `BREAKPOINT_HIT`

Exemplos de eventos v1:

```json
{
    "schema_version": "1.0",
    "seq": 12,
    "kind": "STATUS",
    "event": "RESET",
    "time": 0.0,
    "level": "INFO",
    "source": "lens",
    "message": "Simulation reset",
    "data": {"seed": 42}
}
```

```json
{
    "schema_version": "1.0",
    "seq": 57,
    "kind": "BREAKPOINT",
    "event": "BREAKPOINT_HIT",
    "time": 24.0,
    "level": "INFO",
    "source": "lens",
    "message": "Breakpoint hit",
    "data": {
        "breakpoint_id": 3,
        "label": "fila cheia",
        "condition": "len(resources['Queue'].queue) > 5",
        "hit_count": 2,
        "pause_on_hit": true,
        "edge": "rising"
    }
}
```

---

### 7) Exemplo de uso mínimo (contrato v1)

```python
import simpylens


def model(env):
    pass


lens = simpylens.Lens(model=model)
lens.show()
```
