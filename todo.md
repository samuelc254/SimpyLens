- corrigir as animações/gerenciamento das animações, elas não estão sendo corretamente identificadas

- melhorar desing dos "blocos" para representar melhor as filas os pedidos e para as stores mostrar melhor os produtos

- adicionar modo headless para rodar a simulação sem interface gráfica, apenas com os break points programáticos e logs

- adicionar controle da seed para quando a simulação for resetada, ela possa ser reproduzida exatamente igual

- corrigir gif do readme para rodar em loop

- adicionar testes unitarios

- adicionar rewind step (avaliar a viabilidade)

- remover alias de time para breakpoint

- deixar tamanho do log salvo configuravel e adicionar opção de salvar o log em um arquivo

- refatorar viewer para não ser mais publico e deixar o manager como ponto de acesso principal

- adicionar coleta de métricas

- adicionar teste de alterar breakpoints com a simulação rodando






monkey_patch (para coleta de metricas) - dar outro nome para não confundir com o patch que é aplicado para o viewer (nome ex: `MetricsPatch.apply()`) (não dependencia do manager, deve ser algo que o usuário possa usar mesmo sem usar o viewer manager ou breakpoints)
monkey_patch (para coleta de dados para o viewer) (nome ex: `TrackingPatch.apply()`) (também não pode ser dependente do manager, tem que ser algo que o usuário possa usar mesmo sem usar o viewer manager ou breakpoints para fazer o tracking personalizado se quiser)
manager de simulação (`Manager`) (o "core" de ferenciamento da biblioteca, ele quem gerencia as facilidades prontas como breakpoints, logs e o viewer, mas as metricas e tracking são independentes e podem ser usados sem o manager) (o manager deve ter capacidade de rodar sozinho sem o viewer, assim o usuario pode usar a solução que preferir de visualização)
    controle da seed (`manager.seed`) (para permitir simulações reproduzíveis, mesmo quando resetadas)
    sistema de breakpoints (`manager.add_breakpoints()`) (para usar breakpoint não tem como não ter o manager da biblioteca) (os breakpoints devem poder ser usados mesmo sem o viewer, mas eles vão depender do manager)
    viewer (`manager.viewer.mainloop()`) (a interface grafica é a maior facilidade da biblioteca para o usuario analisar a simulação, deve ser como uma ferramenta que não tem intuido de alterar a simulação, apenas ferramentas que facilitem testar e analisar o que existe)


## API pública mínima (v1)

Objetivo: definir o contrato oficial para a v1 e evitar mudanças quebrando integração de usuários.

### 1) Classe `Manager` (entrada principal)

Construtor:
- `Manager(model=None, title="SimPyLens", gui=True, seed=42)`

Contrato do parâmetro `model`:
- `model` deve ser uma função/callable que recebe exatamente o ambiente de simulação como primeiro argumento.
- assinatura esperada: `def model(env: simpy.Environment): ...`

Métodos oficiais:
- `set_model(model)`
- `set_seed(seed)`
- `run()` (para simulação sem gui roda a simulação normalmente apenas com breakpoints e logs, para simulação com gui é equivalente a usar o `show()` e em seguida clicar no play do viewer (como é equivalente do `show()` + pressionar play o run também é bloqueante quando gui=True))
- `step()` (independente do gui, avança a simulação em um passo, se gui = True, tem o mesmo efeito que clicar no botão de step do viewer)
- `reset()` (reinicia a simulação, recriando o ambiente e reaplicando a seed, se gui = True, tem o mesmo efeito que clicar no botão de reset do viewer)
- `add_breakpoint(condition, label=None, enabled=True, pause_on_hit=True, edge="none")` 
- `remove_breakpoint(breakpoint_id)`
- `clear_breakpoints()`
- `set_breakpoint_enabled(breakpoint_id, enabled)`
- `set_breakpoint_pause_on_hit(breakpoint_id, pause_on_hit)`
- `list_breakpoints()` (retornar uma lista de uma copia dos objetos de breakpoint atuais, sendo todos os atributos públicos de cada breakpoint, como id, condição, label, etc)
- `show()` (inicia o gui e de forma bloqueante (como o show do matplot), para simulações sem gui, retorna um valor seguro)
- `get_logs()` (retorna um json (a raiz do json deve ser uma lista e cada log é um item dessa lista))
- `set_log_capacity(capacity)` (define a capacidade máxima de itens do log, ou seja, quantos eventos ele deve armazenar antes de começar a descartar os mais antigos, valor padrão 1000)



Atributos públicos esperados:
- `manager.model` (apenas leitura, para escrita usar `set_model()`)
- `manager.seed` (apenas leitura, para escrita usar `set_seed()`)
- `manager.title`   (apenas leitura, definido no construtor)
- `manager.gui` (apenas leitura)

Regras de comportamento v1:
- `reset()` sempre recria o ambiente e reaplica `seed`.
- `run()` e `show()` sem `model` definido não deve quebrar (retorno seguro).
- breakpoints funcionam com ou sem UI (dependem do `Manager`).
- quando `gui=True`, o `Manager` é responsável por criar e gerenciar o ciclo de vida do viewer.
- `Viewer` não faz parte da API pública da v1.

---

### 2) Componente interno `Viewer` (não público)

Diretriz de arquitetura:
- `Viewer` é interno da biblioteca e não deve ser usado como ponto de entrada pelo usuário final.
- somente o `Manager` pode criar e gerenciar o `Viewer`.

Objetivo do componente:
- Visualizar e inspecionar a simulação.
- Não alterar regras de negócio do modelo do usuário.

Contrato de produto:
- não exportar `Viewer` como API oficial da v1.
- exemplos e documentação devem usar apenas `Manager` como entrada.

---

### 3) Patch de tracking (independente)

Classe pública proposta:
- `TrackingPatch.apply()`

Escopo:
- Coleta de dados de tracking para visualização/log.
- Uso independente de `Manager` e `Viewer`.

Contrato mínimo:
- Aplicação idempotente (chamar duas vezes não deve quebrar).
- Não exigir UI para funcionar.

---

### 4) Patch de métricas (independente)

Classe pública proposta:
- `MetricsPatch.apply()`

Escopo:
- Coleta de métricas (contadores, tempos, throughput, etc).
- Uso independente de `Manager`, `Viewer` e breakpoints.

Contrato mínimo:
- Aplicação idempotente.
- API de leitura/export de métricas definida e estável na v1.

---

### 5) Convenções gerais da API v1

- Nome oficial para função de entrada do usuário: `model`.
- Não usar alias legados na API pública v1.
- Métodos públicos devem ter docstring com exemplo curto.
- Alterações breaking só em v2+.

---

### 6) Exemplo de uso mínimo (contrato v1)

```python
import simpylens


def model(env):
    pass


manager = simpylens.Manager(model=model, with_ui=True, seed=42)
manager.run()
manager.viewer.mainloop()
```
