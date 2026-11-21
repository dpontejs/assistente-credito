# Fatia 1 — Servidor MCP de crédito: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** servidor MCP próprio com calculadoras, taxas reais do BCB (com cache) e perfil persistente em SQLite, testado sem rede.
**Architecture:** lógica pura no pacote `credito/` (`calc`, `rates`, `profiles`); `servers/credit_server.py` é só a casca FastMCP que valida a entrada, chama o pacote e formata em pt-BR. O servidor é montado por uma fábrica `build_server(db_path, rates)` para os testes injetarem banco temporário e cliente de taxas falso.
**Tech Stack:** Python 3.12, uv, fastmcp 4.x, pydantic 2, httpx, sqlite3 (stdlib), pytest.
**Spec:** `docs/features/assistente-credito.md`

## Global Constraints

- Comentários, docstrings (uma frase), mensagens e saídas das ferramentas em pt-BR; identificadores em inglês (padrão do repo do professor).
- Taxas sempre em **% ao mês** (`5.0` = 5% a.m.), como na API do BCB. Docstring de cada ferramenta diz isso.
- Ferramenta nunca lança exceção para o cliente: erro de entrada ou de rede vira string `"erro: ..."` (padrão de `course.py`).
- Valores em reais formatados `R$ 1.234,56`.
- `pytest` roda sem rede e sem chave; o único teste com rede é marcado `@pytest.mark.network` e fica fora do padrão (`-m "not network"` no `addopts`).
- Mensagens de commit em pt-BR, `tipo: mensagem`, sem escopo e sem coautoria.

## Review Focus

- Taxa 0% na Tabela Price → parcela = saldo / n, sem divisão por zero (teste na Tarefa 1).
- Parcela que não cobre os juros, ou saldo/prazo ≤ 0 → `"erro: ..."`, nunca laço infinito nem exceção (Tarefas 1 e 4).
- Modalidade desconhecida vinda do modelo (ex.: "Cartão rotativo") → erro que lista as válidas (Tarefa 4).
- BCB fora do ar sem cache → `"erro: ..."`; com cache → resposta marcada "dados em cache de <data>" (Tarefa 2).
- `remove_debt` com `debt_id` de outro usuário não apaga nada (Tarefa 3).

---

### Task 1: Projeto e calculadoras

**Files:** Create `pyproject.toml`, `.gitignore`, `.env.example`, `credito/__init__.py`, `credito/calc.py`, `tests/test_calc.py`

**Interfaces — Produces:**
- `price_installment(balance: float, monthly_rate: float, n: int) -> float`
- `payoff(balance: float, monthly_rate: float, payment: float) -> Payoff` — `Payoff(months: int, total_interest: float)` (dataclass)
- `portability(balance: float, n_left: int, current_rate: float, new_rate: float) -> Portability` — `Portability(current_installment, new_installment, total_savings: float)`
- `brl(value: float) -> str`
- Entradas inválidas levantam `ValueError` com mensagem em pt-BR.

- [ ] **Passo 1:** `pyproject.toml` com `requires-python = ">=3.12"`, deps `fastmcp>=4,<5`, `pydantic>=2`, `httpx`; extra `dev = ["pytest"]`; `[tool.pytest.ini_options] addopts = '-m "not network"'`, marker `network`. `.gitignore`: `.venv/ .env data/*.db data/rates_cache.json __pycache__/ .pytest_cache/`. `.env.example` com `GOOGLE_API_KEY=`. Rodar `uv sync --extra dev`.
- [ ] **Passo 2: testes que falham** em `tests/test_calc.py`:
```python
assert round(price_installment(1000, 5, 12), 2) == 112.83
assert price_installment(1200, 0, 12) == 100.0
assert payoff(1000, 5, 100) == Payoff(months=15, total_interest=pytest.approx(421.07, abs=0.01))
with pytest.raises(ValueError, match="não cobre os juros"): payoff(1000, 5, 50)
with pytest.raises(ValueError): price_installment(1000, 5, 0)
with pytest.raises(ValueError): price_installment(-1, 5, 12)
p = portability(15000, 36, 2.1, 1.81)
assert (round(p.current_installment, 2), round(p.new_installment, 2), round(p.total_savings, 2)) == (597.99, 570.69, 982.76)
assert brl(1234.5) == "R$ 1.234,50"
```
- [ ] **Passo 3:** `uv run pytest tests/test_calc.py` → FAIL (import).
- [ ] **Passo 4:** implementar `credito/calc.py`. `payoff` simula mês a mês (juros sobre o saldo, última parcela parcial); recusa `payment <= balance * rate` com "a parcela não cobre os juros do mês" e corta em 600 meses com `ValueError`.
- [ ] **Passo 5:** `uv run pytest` → PASS. Commit `feat: calculadoras de parcela, quitacao e portabilidade`.

### Task 2: Taxas de mercado do BCB com cache

**Files:** Create `credito/rates.py`, `tests/test_rates.py`

**Interfaces — Produces:**
- `MODALITIES: dict[str, str]` — chave interna → nome exato no BCB: `cartao_rotativo`→"Cartão de crédito - rotativo total - Prefixado", `cartao_parcelado`→"Cartão de crédito - parcelado - Prefixado", `cheque_especial`→"Cheque especial - Prefixado", `pessoal`→"Crédito pessoal não consignado - Prefixado", `consignado_inss`/`consignado_privado`/`consignado_publico`→"Crédito pessoal consignado INSS/privado/público - Prefixado", `veiculo`→"Aquisição de veículos - Prefixado".
- `MarketRate(kind, period_start: str, median: float, n_institutions: int, from_cache: bool)` (dataclass)
- `class RatesClient: __init__(self, cache_path: Path, fetch: Callable[[str, dict], dict] = http_get)`; `market_rate(self, kind: str) -> MarketRate`; levanta `KeyError` para modalidade desconhecida e `RatesUnavailable` sem rede e sem cache.

**Fonte:** `https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/TaxasJurosDiariaPorInicioPeriodo`, `$format=json`. Duas chamadas: (1) `$filter=Segmento eq 'PESSOA FÍSICA' and Modalidade eq '<nome>'`, `$orderby=InicioPeriodo desc`, `$top=1` → período mais recente; (2) mesmo filtro + `InicioPeriodo eq '<data>'`, `$top=1000` → `TaxaJurosAoMes` de cada banco. Estatística: **mediana** (decisão: robusta a outliers; o texto da ferramenta diz "mediana de N bancos"). Sucesso grava `{kind: {...}}` no cache JSON.

- [ ] **Passo 1: testes que falham** com `fetch` falso (dicionário de respostas, sem rede): mediana de `[10, 15.79, 20]` → `15.79`, `n_institutions == 3`, `from_cache is False`; segunda instância com `fetch` que levanta `httpx.ConnectError` lê o cache → `from_cache is True`, mesmo `median`; sem cache → `RatesUnavailable`; `market_rate("hipoteca")` → `KeyError`. Mais `test_bcb_real` marcado `network`: `market_rate("cartao_rotativo").median > 1`.
- [ ] **Passo 2:** `uv run pytest tests/test_rates.py` → FAIL.
- [ ] **Passo 3:** implementar `credito/rates.py` (`http_get` com `httpx.get(url, params=..., timeout=30)`).
- [ ] **Passo 4:** `uv run pytest` → PASS; `uv run pytest -m network` → PASS (confere o endpoint real). Commit `feat: taxas de mercado do BCB com cache local`.

### Task 3: Perfil persistente em SQLite

**Files:** Create `credito/profiles.py`, `tests/test_profiles.py`

**Interfaces — Produces:**
- `Debt(BaseModel)`: `kind: Literal[<chaves de MODALITIES>]`, `creditor: str`, `balance: float = Field(gt=0)`, `monthly_rate: float = Field(ge=0)`, `installments_left: int | None = None`
- `class ProfileStore: __init__(self, db_path: Path)` (cria tabelas do spec se faltarem); `seed(self) -> None` (idempotente); `get_profile(user_id) -> dict | None` → `{"id", "name", "income", "debts": [{"id", **Debt}], "plan": str | None}`; `save_debt(user_id, debt: Debt) -> int` (upsert por `UNIQUE(user_id, kind, creditor)`, devolve o id); `remove_debt(user_id, debt_id) -> bool` (`DELETE ... WHERE id=? AND user_id=?`); `save_plan(user_id, text) -> None` (insere; `get_profile` devolve o mais recente).

**Seed** (credores fictícios, nenhum banco real): `ana` Ana Souza, renda 4500 — `cartao_rotativo` Banco Alfa 4000 @ 14.0; `consignado_privado` Banco Beta 15000 @ 2.1, 36×. `bruno` Bruno Lima, renda 3200 — `cheque_especial` Banco Gama 2500 @ 7.9; `pessoal` Financeira Delta 8000 @ 6.5, 24×. `carla` Carla Mendes, renda 7800 — `veiculo` Banco Alfa 32000 @ 2.4, 40×; `cartao_parcelado` Banco Beta 3000 @ 9.0, 10×.

- [ ] **Passo 1: testes que falham** (`tmp_path`): `test_save_debt_idempotente` (salvar a mesma dívida duas vezes com saldos 4000 e 3500 → 1 dívida, saldo 3500, mesmo id); `test_remove_debt_de_outro_usuario` (`remove_debt("bruno", <id da Ana>)` → `False` e a dívida da Ana continua); `test_seed_idempotente` (seed 2× → 3 usuários, 6 dívidas); `test_plano_mais_recente`; `test_usuario_inexistente` → `None`; `Debt(kind="hipoteca", ...)` → `ValidationError`.
- [ ] **Passo 2:** `uv run pytest tests/test_profiles.py` → FAIL.
- [ ] **Passo 3:** implementar `credito/profiles.py` (`sqlite3`, uma conexão por chamada, `INSERT ... ON CONFLICT(user_id, kind, creditor) DO UPDATE`).
- [ ] **Passo 4:** `uv run pytest` → PASS. Commit `feat: perfil persistente com dividas e planos`.

### Task 4: Servidor FastMCP

**Files:** Create `servers/credit_server.py`, `tests/test_server.py`, `README.md` (seção curta "Servidor MCP": como rodar)

**Interfaces — Consumes:** Tarefas 1–3. **Produces:** `build_server(db_path: Path, rates: RatesClient) -> FastMCP` com as ferramentas do spec, nomes e parâmetros exatos: `market_rate(modality)`, `compare_rate(modality, monthly_rate)`, `simulate_payoff(balance, monthly_rate, payment)`, `simulate_installments(balance, monthly_rate, n)`, `simulate_portability(balance, n_left, current_rate, new_rate)`, `get_profile(user_id)` (JSON `ensure_ascii=False`), `save_debt(user_id, kind, creditor, balance, monthly_rate, installments_left=None)`, `remove_debt(user_id, debt_id)`, `save_plan(user_id, plan)`. Sob `__main__`: `os.environ["FASTMCP_LOG_LEVEL"]="WARNING"`, `build_server(Path("data/profiles.db"), RatesClient(Path("data/rates_cache.json")))`, `seed()`, `mcp.run(show_banner=False)` (stdio).

- [ ] **Passo 1: testes que falham**, via cliente em memória (`fastmcp.Client(server)` dentro de `asyncio.run`, sem plugin): as 9 ferramentas listadas; `simulate_installments(1000, 5, 12)` contém `"R$ 112,83"`; `simulate_payoff(1000, 5, 50)` começa com `"erro:"`; `compare_rate("cartao_rotativo", 14)` com `RatesClient` falso (mediana 15.79) contém `"0,89"` e "abaixo da mediana"; `compare_rate("Cartão rotativo", 14)` → `"erro:"` listando `cartao_rotativo`; `market_rate` sem rede e sem cache → `"erro:"`; `save_debt("ana", "cartao_rotativo", "Banco Alfa", 3500, 14)` 2× + `get_profile("ana")` → continua com 2 dívidas e o rotativo com saldo 3500.
- [ ] **Passo 2:** `uv run pytest tests/test_server.py` → FAIL.
- [ ] **Passo 3:** implementar o servidor; cada ferramenta com docstring de uma frase dizendo unidades (% a.m., R$) e as modalidades válidas; `ValueError`/`KeyError`/`ValidationError`/`RatesUnavailable` → `"erro: <mensagem>"`.
- [ ] **Passo 4:** `uv run pytest` → PASS. Smoke stdio: `uv run fastmcp list servers/credit_server.py` (ou o equivalente do fastmcp 4 para listar ferramentas) mostra as 9. Commit `feat: servidor MCP de credito`.
