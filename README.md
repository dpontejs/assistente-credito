# Assistente de dívidas e crédito

Trabalho da Unidade II de IA Agêntica (UFRN, 2026.2). Em construção; o desenho
está em [`docs/features/assistente-credito.md`](docs/features/assistente-credito.md).

## Instalação

```bash
uv sync --extra dev
cp .env.example .env   # preencher GOOGLE_API_KEY
```

## Servidor MCP

```bash
uv run python servers/credit_server.py
```

Roda em stdio e cria `data/profiles.db` com três usuários fictícios (`ana`,
`bruno`, `carla`). As taxas de mercado vêm da API de dados abertos do Banco
Central ([taxas de juros por instituição](https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/)),
com cache em `data/rates_cache.json` para quando a API não responder.

| Ferramenta | O que faz |
|---|---|
| `market_rate` | mediana da taxa (% a.m.) dos bancos na modalidade |
| `compare_rate` | taxa do cliente contra a mediana |
| `simulate_payoff` | meses e juros para quitar com parcela fixa |
| `simulate_installments` | parcela pela Tabela Price |
| `simulate_portability` | economia ao portar para outra taxa |
| `get_profile`, `save_debt`, `remove_debt`, `save_plan` | perfil persistente |

## Corpus

Leis e normas oficiais sobre crédito ao consumidor, limpas e divididas por artigo
em `data/docs/` (fontes, vigência e o que ficou de fora em
[`data/docs/FONTES.md`](data/docs/FONTES.md)), mais notas curadas em
`data/docs/notas/` para decisões que os textos oficiais ainda não refletem.

```bash
uv run python scripts/download_corpus.py   # baixa de novo do Planalto e do BCB
```

O índice (`data/chroma/`) usa embeddings `gemini-embedding-001` e é criado na
primeira execução do agente; na cota gratuita leva uns 3 minutos.

## Agente

Grafo LangGraph em `credito/graph.py`: guarda de entrada → perfil → agente ⇄
ferramentas, com avaliação e reescrita da busca nas normas → guarda de saída.
`credito/assistant.py` liga o Gemini (`CREDITO_MODEL`, padrão
`google_genai:gemini-3.5-flash-lite`), os dois servidores MCP (o próprio e o
`mcp-server-time`, via `uvx`), a busca nas normas, as skills de `skills/` e o
checkpointer SQLite (`data/checkpoints.db`).

```bash
uv run python scripts/chat.py --user ana --thread t1 "Meu cartão cobra 14% ao mês. É normal?"
```

## Interface

```bash
uv run streamlit run app.py
```

Barra lateral com o seletor de usuário fictício (Ana, Bruno, Carla), o botão
"Nova conversa" e o painel do perfil: renda, total devido e cada dívida com a
taxa comparada à mediana do mercado (🔴 acima, 🟢 abaixo). Cada resposta mostra
as ferramentas e as skills usadas. Trocar de usuário abre outra conversa, porque
cada conversa pertence a quem a começou.

## Testes

```bash
uv run pytest              # sem rede
uv run pytest -m network   # confere a API real do BCB
```
