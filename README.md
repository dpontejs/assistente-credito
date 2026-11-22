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

## Testes

```bash
uv run pytest              # sem rede
uv run pytest -m network   # confere a API real do BCB
```
