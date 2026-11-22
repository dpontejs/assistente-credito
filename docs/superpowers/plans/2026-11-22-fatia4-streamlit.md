# Fatia 4 — Interface Streamlit: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `app.py` em Streamlit com chat, seletor de usuário fictício, botão "Nova conversa", painel do perfil (renda, dívidas, taxa contra a mediana do mercado, total) e, em cada resposta, as ferramentas e skills usadas.
**Architecture:** lógica pura em `credito/ui.py` (turnos a partir das mensagens, dados do painel), testada sem Streamlit. `credito/runner.py` mantém o assistente assíncrono (servidores MCP abertos) vivo numa thread com loop próprio e expõe chamadas síncronas, porque o Streamlit reexecuta o script a cada interação. `app.py` segue o molde de `apps/invoices/app.py` do professor (`st.cache_resource`, `thread_id` em `st.session_state`, conversa redesenhada do checkpointer).
**Tech Stack:** streamlit 1.67 (`streamlit.testing.v1.AppTest` nos testes), o resto das fatias anteriores.
**Spec:** `docs/features/assistente-credito.md` (seção UI).

## Global Constraints

- Constraints das fatias anteriores continuam; textos da interface em pt-BR.
- Trocar de usuário no seletor abre uma conversa nova (a conversa é presa ao dono, fatia 3); cada usuário guarda o seu `thread_id` em `st.session_state.threads`.
- O painel lê o perfil direto do `ProfileStore` (mesmo SQLite do servidor) e as medianas do `RatesClient` com cache, para não chamar o modelo nem o MCP só para desenhar a tela.
- Nada de chave ou dado sensível na tela além do perfil fictício.

## Review Focus

- Turno recusado mostra o marcador "[mensagem bloqueada pelo guardrail]" e a recusa, sem expander vazio (Task 1).
- Dívida sem mediana disponível (BCB fora e sem cache) aparece sem a comparação, não quebra o painel (Task 1).
- Erro do assistente (429, servidor MCP caiu) vira aviso na tela, não traceback (Task 3).
- Clicar "Nova conversa" não apaga a conversa anterior do checkpointer (só troca o `thread_id`) (Task 3).
- Fechar o app encerra a thread do runner sem deixar processos MCP órfãos (Task 2).

---

### Task 1: Lógica da interface

**Files:** Create `credito/ui.py`, `tests/test_ui.py`

**Interfaces — Produces:**
- `Turn` (dataclass): `question: str`, `answer: str`, `tools: list[str]`, `skills: list[str]`.
- `turns(messages: list[BaseMessage]) -> list[Turn]` — um por `HumanMessage`; resposta = última `AIMessage` sem `tool_calls` do turno (texto via `as_text`); `tools` = nomes chamados, exceto `load_skill`; `skills` = `args["name"]` das chamadas a `load_skill`; turno ainda sem resposta fica com `answer=""`.
- `KIND_NAMES: dict[str, str]` — `cartao_rotativo` → "Cartão (rotativo)", etc., para as 8 modalidades.
- `PanelRow` (dataclass): `creditor`, `kind`, `balance: str` (R$), `rate: str` (% a.m.), `market: str | None` ("acima da mediana (15,79%)"/"abaixo..."), `above_market: bool | None`.
- `panel_rows(profile: dict, median_for: Callable[[str], float | None]) -> list[PanelRow]`.
- `scripts/chat.py` passa a usar `turns()` (remove `turn_summary`).

- [ ] **Step 1: testes que falham:** `turns` com dois turnos (o 1º com `credito_compare_rate`, `search_norms` e `load_skill(name="plano-de-quitacao")`; o 2º sem ferramentas) → tools/skills certos em cada um; turno recusado → `question == "[mensagem bloqueada pelo guardrail]"`, `tools == []`; resposta em blocos (`[{"type": "text", "text": "oi"}]`) → `"oi"`; `panel_rows` da Ana com `median_for` falso (rotativo 15,79) → linha do rotativo `"R$ 4.000,00"`, `"14,00%"`, `above_market is False`; `median_for` devolvendo `None` → `market is None`.
- [ ] **Step 2–4:** FAIL → implementar → PASS. Commit `feat: logica da interface (turnos e painel)`.

### Task 2: Runner em segundo plano

**Files:** Create `credito/runner.py`, `tests/test_runner.py`

**Interfaces — Produces:** `class AssistantRunner: __init__(self, factory: Callable[[], AbstractAsyncContextManager] = open_assistant, timeout: float = 180)`; `ask(user_id: str, thread_id: str, text: str) -> list[BaseMessage]` (mensagens da thread depois do turno); `history(thread_id: str) -> list[BaseMessage]` (`graph.aget_state`); `close()`. A thread do runner abre o `factory()` uma vez, sinaliza pronto e fica no loop até `close()`; erros de abertura são relançados em `ask`/`history`.

- [ ] **Step 1: testes que falham** com um factory falso (contexto assíncrono que devolve um objeto com `graph.ainvoke`/`aget_state` falsos e registra entrada/saída): `ask` devolve as mensagens; duas chamadas reaproveitam a mesma abertura (factory entrou 1 vez); `close()` sai do contexto; factory que lança → `ask` lança a mesma exceção.
- [ ] **Step 2–4:** FAIL → implementar → PASS. Commit `feat: runner do assistente para o streamlit`.

### Task 3: App Streamlit

**Files:** Create `app.py`, `tests/test_app.py`; Modify `README.md` (seção "Interface").

**Interfaces — Consumes:** `turns`, `panel_rows`, `KIND_NAMES` (Task 1); `AssistantRunner` (Task 2); `ProfileStore`, `RatesClient`, `brl`. `app.py` expõe `get_runner()` (`@st.cache_resource`) e `median_for(kind)` (`@st.cache_data(ttl=3600)`, `None` se o BCB e o cache falharem).

- [ ] **Step 1: testes que falham** com `AppTest.from_file("app.py")` e `credito.runner.AssistantRunner` trocado por um falso (`monkeypatch` antes de rodar): a barra lateral tem o seletor com Ana Souza, Bruno Lima e Carla Mendes e o botão "Nova conversa"; o painel mostra o total da Ana; enviar "quanto eu devo?" no `chat_input` chama `ask("ana", <thread>, ...)` e a resposta aparece com um expander que lista as ferramentas; clicar "Nova conversa" muda o `thread_id`; trocar para Bruno usa outro `thread_id`; runner que lança mostra `st.error` com a mensagem, sem exceção no AppTest.
- [ ] **Step 2–4:** FAIL → implementar → PASS.
- [ ] **Step 5: verificação real:** `uv run streamlit run app.py --server.headless true` responde em `/_stcore/health`; conversa de ponta a ponta pelo navegador (ou registrar que foi feita só pelo AppTest com runner real, se não houver navegador). Commit `feat: interface streamlit com painel do perfil`.
