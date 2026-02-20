# SimPy 2D Visualizer (Zero-Invasion)

Uma biblioteca Python *plug-and-play* projetada para gerar visualizações 2D animadas de modelos de simulação a eventos discretos (DES) baseados em SimPy, com **zero alteração** na lógica de negócios do seu código original.

## 🎯 O Problema que Resolvemos
O SimPy é o padrão ouro para simulação em Python, permitindo integração profunda com ecossistemas de dados. No entanto, sua natureza estritamente textual e baseada em terminal dificulta a validação do modelo e a apresentação de resultados para *stakeholders* não-técnicos. 

Desenvolvido com o rigor da engenharia de software de simulação e pensado para a validação de sistemas complexos de automação e robótica, este projeto atua como uma ponte. Ele permite que você mantenha a flexibilidade e o poder analítico do código em Python, mas ganhe a capacidade de convencimento visual encontrada em softwares comerciais caros, tudo de forma transparente via *Monkey Patching*.

## 🚀 Escopo e Funcionalidades (Fase 1 / MVP)
O foco central deste projeto é a **validação visual não-invasiva**. 

* **Filosofia "Zero-Invasion":** A interface gráfica apenas "escuta" os eventos. Seu código SimPy permanece puro, focado em regras de negócio e livre de amarras de front-end.
* **Cobertura do SimPy Core:** Interceptação visual nativa para `Resource`, `Container` e `Store` (com expansão de escopo planejada para `PriorityResource` e `PreemptableResource`).
* **Layout Fluido Inteligente (Masonry):** Motor de alocação visual que organiza automaticamente os recursos na tela de forma otimizada, suportando navegação via *Pan* e *Zoom* para plantas de grande escala.
* **Extração de Métricas Limpa:** A arquitetura intercepta dados das filas e usos das máquinas, deixando o caminho preparado para exportação direta para análise de dados (ex: DataFrames do Pandas) ao término da simulação.

## 🛑 O Que Este Projeto NÃO É (Anti-Escopo)
Para garantir alta performance, manutenção viável e foco no desenvolvedor, este projeto define limites rígidos:

* **Não é um modelador Drag-and-Drop:** Não há construção visual de modelos (estilo Arena). A modelagem continua sendo escrita exclusivamente em código Python.
* **Não permite controle de parâmetros via GUI:** O código Python é a única *Source of Truth* (Fonte da Verdade). Capacidades ou tempos de processo não são alterados clicando na interface.
* **Não é um gerador de Dashboards:** O projeto foca em animar o fluxo físico (peças, entidades, gargalos). Gráficos estatísticos complexos devem ser gerados externamente utilizando bibliotecas apropriadas (`Matplotlib`, `Seaborn`) alimentadas pelas métricas exportadas.
* **Não é um sistema Web (SaaS):** A interface roda primariamente no Desktop (`tkinter`), evitando o acúmulo desnecessário de complexidade de infraestrutura de redes ou WebSockets nesta etapa de desenvolvimento.

## 🛠️ Como Usar (Exemplo Básico)
Basta importar o módulo de *Monkey Patch* antes de instanciar sua simulação padrão do SimPy:

```python
import monkey_patch
import gui
import simu # Seu arquivo com a simulação original

# 1. Aplica a interceptação silenciosa das classes do SimPy
monkey_patch.apply_patch()

# 2. Inicia a interface gráfica
if __name__ == "__main__":
    app = gui.SimPyVisualizer()
    app.mainloop()