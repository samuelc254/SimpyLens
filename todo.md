# TODO v1 — SimpyLens

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

---

## 8) Novo padrão de logs JSON (v1 — proposta de refatoração)

### Diagnóstico dos problemas no formato atual

O JSON gerado atualmente apresenta os seguintes problemas:

1. **`event` sempre `"UNKNOWN"`** nos logs de tracking: o `tracking_patch.py` emite apenas `kind` sem preencher `event`, então o normalizador usa o fallback `"UNKNOWN"` — campo sem valor semântico real.
2. **`detail` e `data` redundantes**: o normalizador em `sim_manager.py` copia `detail` para `data` indiscriminadamente, gerando dois campos com o mesmo conteúdo.
3. **Campos de payload no nível raiz**: logs de `RESOURCE` colocam `action`, `from`, `to`, `process`, `resource` na raiz do objeto junto com os campos obrigatórios (`schema_version`, `seq`, `kind`, etc.), misturando metadados de envelope com dados de evento.
4. **STEP_AFTER de valor questionável**: o log `phase: "after"` é emitido somente quando o processo ativo difere do esperado, criando uma inconsistência — o usuário não sabe quando esperar esse log.
5. **`kind: "STATUS"` usado para breakpoints**: `BREAKPOINT_HIT` e `BREAKPOINT_ERROR` deveriam ter `kind: "BREAKPOINT"`, não `"STATUS"`.
6. **`expression` duplica `condition`**: dois campos com o mesmo valor no payload de breakpoint.
7. **`source` invariável**: o campo `source` é sempre `"lens"` em todos os eventos, sem distinção real entre quem originou o evento.
8. **`level` sem uso prático**: todos os logs têm `level: "INFO"` e nunca é usado para filtrar ou estilizar na interface.

---

### Estrutura envelope obrigatória (todos os eventos)

Todo objeto de log deve conter exatamente estes campos de envelope na raiz:

| Campo           | Tipo    | Descrição                                                         |
|-----------------|---------|-------------------------------------------------------------------|
| `schema_version`| string  | Versão do esquema. Fixo `"1.0"` na v1.                           |
| `seq`           | int     | Contador crescente e único por execução (reset no `RESET`).       |
| `time`          | float   | Tempo da simulação no momento do evento.                          |
| `kind`          | string  | Categoria alta do evento. Ver tabela de kinds abaixo.             |
| `event`         | string  | Tipo específico do evento dentro do kind. Ver tabela abaixo.      |
| `level`         | string  | Severidade: `"DEBUG"`, `"INFO"`, `"WARN"`, `"ERROR"`.            |
| `source`        | string  | Componente que originou o evento: `"lens"`, `"tracking"`.         |
| `message`       | string  | Texto curto legível para humano, descrevendo o evento.            |
| `data`          | object  | Payload específico do evento. Pode ser `null` se não há payload.  |

> Não deve existir nenhum campo de payload fora de `data`. A raiz do objeto é exclusiva dos campos de envelope listados acima.

---

### Tabela de `kind` e `event` v1

| `kind`        | `event`             | Origem         | Descrição                                                       |
|---------------|---------------------|----------------|-----------------------------------------------------------------|
| `SIM`         | `RESET`             | `lens`         | Simulação foi reiniciada.                                       |
| `SIM`         | `RUN_COMPLETE`      | `lens`         | Simulação terminou (fila vazia).                                |
| `STEP`        | `STEP_BEFORE`       | `tracking`     | Antes de executar um passo do SimPy.                            |
| `STEP`        | `STEP_AFTER`        | `tracking`     | Após passo, quando o processo ativo mudou inesperadamente.      |
| `RESOURCE`    | `REQUEST`           | `tracking`     | Processo requisitou um recurso.                                 |
| `RESOURCE`    | `RELEASE`           | `tracking`     | Processo liberou um recurso.                                    |
| `RESOURCE`    | `PUT`               | `tracking`     | Processo depositou item/quantidade em Store/Container.          |
| `RESOURCE`    | `GET`               | `tracking`     | Processo retirou item/quantidade de Store/Container.            |
| `BREAKPOINT`  | `BREAKPOINT_HIT`    | `lens`         | Condição de breakpoint foi satisfeita.                          |
| `BREAKPOINT`  | `BREAKPOINT_ERROR`  | `lens`         | Erro ao avaliar condição de breakpoint.                         |
| `STATUS`      | `MESSAGE`           | `lens`         | Mensagem genérica de texto (fallback para strings livres).      |

---

### Schemas de `data` por evento

#### `SIM / RESET`
```json
"data": {
    "seed": 42
}
```

#### `SIM / RUN_COMPLETE`
```json
"data": null
```

#### `STEP / STEP_BEFORE`
```json
"data": {
    "step": 3,
    "sim_event": "Timeout",
    "delay": 1.5,
    "resource": "counter",
    "process": "customer",
    "triggering": ["customer", "source"]
}
```
> Campos opcionais: `delay` (só presente em `Timeout`), `resource` (só em eventos de resource), `process` (só em `Process`), `triggering` (lista de nomes de processos esperando o evento). Somente campos aplicáveis ao tipo de evento devem estar presentes.

#### `STEP / STEP_AFTER`
```json
"data": {
    "step": 3,
    "active_process": "customer"
}
```
> Emitido apenas quando o processo ativo após o passo difere do processo esperado antes. `active_process` é `"-"` se nenhum processo está ativo.

#### `RESOURCE / REQUEST` e `RESOURCE / RELEASE`
```json
"data": {
    "resource": "counter",
    "process": "customer",
    "from": "<START>",
    "to": "counter"
}
```
> `from`/`to` descrevem o movimento do processo no grafo de recursos. `from: "<START>"` quando o processo ainda não estava em nenhum recurso. `to: "<IDLE>"` em releases. Não há dados extras além do movimento.

#### `RESOURCE / PUT` e `RESOURCE / GET`
```json
"data": {
    "resource": "warehouse",
    "process": "producer",
    "from": "<START>",
    "to": "warehouse",
    "amount": 5
}
```
> `amount` (para `Container`), `item` (para `Store`) e `filter` (para `FilterStore`) vão diretamente em `data` quando presentes. Campos omitidos quando não aplicáveis.

#### `BREAKPOINT / BREAKPOINT_HIT`
```json
"data": {
    "breakpoint_id": 3,
    "label": "fila cheia",
    "condition": "len(resources['Queue'].queue) > 5",
    "hit_count": 2,
    "pause_on_hit": true,
    "edge": "rising"
}
```

#### `BREAKPOINT / BREAKPOINT_ERROR`
```json
"data": {
    "breakpoint_id": 3,
    "label": "fila cheia",
    "condition": "len(resources['Queue'].queue) > 5",
    "error": "NameError: name 'resources' is not defined"
}
```

#### `STATUS / MESSAGE`
```json
"data": null
```
> `message` no envelope já carrega o texto. `data` é `null`.

---

### Exemplos completos

**RESET:**
```json
{
    "schema_version": "1.0",
    "seq": 1,
    "time": 0.0,
    "kind": "SIM",
    "event": "RESET",
    "level": "INFO",
    "source": "lens",
    "message": "Simulation reset with seed 42",
    "data": {"seed": 42}
}
```

**STEP_BEFORE:**
```json
{
    "schema_version": "1.0",
    "seq": 5,
    "time": 0.0,
    "kind": "STEP",
    "event": "STEP_BEFORE",
    "level": "DEBUG",
    "source": "tracking",
    "message": "Step 3: Timeout | triggering=customer",
    "data": {
        "step": 3,
        "sim_event": "Timeout",
        "delay": 1.5,
        "triggering": ["customer"]
    }
}
```

**RESOURCE REQUEST:**
```json
{
    "schema_version": "1.0",
    "seq": 8,
    "time": 0.0,
    "kind": "RESOURCE",
    "event": "REQUEST",
    "level": "INFO",
    "source": "tracking",
    "message": "customer requested counter",
    "data": {
        "resource": "counter",
        "process": "customer",
        "from": "<START>",
        "to": "counter"
    }
}
```

**RESOURCE RELEASE:**
```json
{
    "schema_version": "1.0",
    "seq": 12,
    "time": 3.86,
    "kind": "RESOURCE",
    "event": "RELEASE",
    "level": "INFO",
    "source": "tracking",
    "message": "customer released counter",
    "data": {
        "resource": "counter",
        "process": "customer",
        "from": "counter",
        "to": "<IDLE>"
    }
}
```

**BREAKPOINT_HIT:**
```json
{
    "schema_version": "1.0",
    "seq": 57,
    "time": 24.0,
    "kind": "BREAKPOINT",
    "event": "BREAKPOINT_HIT",
    "level": "INFO",
    "source": "lens",
    "message": "Breakpoint hit: fila cheia (hits=2)",
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

## 9) Padrão de exibição dos logs na interface (Viewer)

### Formato visual por kind/event

A interface deve exibir cada log como uma linha de texto formatada, nunca como JSON bruto. O formato linha segue o padrão:

```
[TIME] [KIND] MESSAGE | KEY=VALUE | KEY=VALUE
```

Onde:
- `[TIME]` → tempo da simulação com 2 casas decimais, ex: `[3.86]`
- `[KIND]` → o valor do campo `kind`, ex: `[RESOURCE]`, `[STEP]`, `[BREAKPOINT]`
- `MESSAGE` → o campo `message` do envelope (texto legível pronto)
- `| KEY=VALUE` → detalhes extras do `data`, quando relevantes

---

### Regras de exibição por evento

#### `SIM / RESET`
```
[0.00] [SIM] Simulation reset with seed 42
```

#### `SIM / RUN_COMPLETE`
```
[120.50] [SIM] Simulation complete
```

#### `STEP / STEP_BEFORE`
```
[0.00] [STEP ▶ 3] Timeout | triggering=customer | delay=1.5
[0.00] [STEP ▶ 4] Request | resource=counter | triggering=customer
[3.86] [STEP ▶ 8] Release | resource=counter
[3.86] [STEP ▶ 9] Process | process=customer
```
> O número do passo deve ser parte do label `[STEP ▶ N]`. Campos relevantes do `data` são exibidos como `KEY=VALUE` após o `sim_event`.  
> Campos exibidos conforme presença: `resource`, `process`, `delay`, `triggering` (como lista separada por vírgula).

#### `STEP / STEP_AFTER`
```
[3.86] [STEP ◀ 8] active=customer
```
> Estilo distinto (ex: `◀`) para distinguir do `before`. Exibido apenas quando presente, pois já é condicional.

#### `RESOURCE / REQUEST`
```
[0.00] [RESOURCE] customer requested counter  (<START> → counter)
```

#### `RESOURCE / RELEASE`
```
[3.86] [RESOURCE] customer released counter  (counter → <IDLE>)
```

#### `RESOURCE / PUT`
```
[5.00] [RESOURCE] producer put into warehouse  (<START> → warehouse) | amount=5
```

#### `RESOURCE / GET`
```
[6.00] [RESOURCE] consumer got from warehouse  (warehouse → <IDLE>)
```

#### `BREAKPOINT / BREAKPOINT_HIT`
```
[24.00] [BREAKPOINT ●] fila cheia | condition=len(resources['Queue'].queue) > 5 | hits=2
```
> Destaque visual diferenciado (ex: ícone `●` ou cor laranja) para facilitar identificação.

#### `BREAKPOINT / BREAKPOINT_ERROR`
```
[24.00] [BREAKPOINT ✗] fila cheia | condition=len(resources['Queue'].queue) > 5 | error=NameError: name 'resources' is not defined
```
> Deve ter destaque em vermelho.

#### `STATUS / MESSAGE` (fallback)
```
[0.00] [STATUS] <texto livre>
```

---

### Regras gerais de exibição

1. **Nunca exibir JSON bruto** na área de logs — sempre formatar.
2. **Ordenar visualmente por seq** (já é garantido pela ordem de inserção no buffer circular).
3. **Coloração por kind** (opcional, mas recomendado):
   - `RESOURCE` → azul
   - `STEP` → cinza claro
   - `BREAKPOINT_HIT` → laranja
   - `BREAKPOINT_ERROR` → vermelho
   - `SIM` → verde
   - `STATUS` → padrão
4. **Truncar linhas longas** na exibição textual — valores de `condition` e `error` podem ser longos; limitar a `~120 chars` por linha e truncar com `...`.
5. **Campo `message`** deve ser o texto principal da linha — o código de formatação não deve reescrever o conteúdo, apenas enriquecer com dados do `data`.
6. **STEP_BEFORE de eventos internos** sem processo associado (ex: `Condition`, `Initialize`) devem ser exibidos, mas com menor destaque visual (ex: cor mais clara).
