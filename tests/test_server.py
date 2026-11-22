import asyncio
import json
import os

import httpx
import pytest

os.environ.setdefault("FASTMCP_LOG_LEVEL", "WARNING")

from fastmcp import Client  # noqa: E402

from credito.rates import RatesClient  # noqa: E402
from servers.credit_server import build_server  # noqa: E402

TOOLS = {
    "market_rate", "compare_rate", "simulate_payoff", "simulate_installments", "simulate_portability",
    "get_profile", "save_debt", "remove_debt", "save_plan",
}


def fake_fetch(url: str, params: dict) -> dict:
    """Responde como o BCB com mediana 15.79 em 2026-10-29."""
    if params.get("$top") == 1:
        return {"value": [{"InicioPeriodo": "2026-10-29"}]}
    return {"value": [{"TaxaJurosAoMes": r} for r in (10, 15.79, 20)]}


def offline_fetch(url: str, params: dict) -> dict:
    raise httpx.ConnectError("sem rede")


@pytest.fixture
def server(tmp_path):
    return build_server(tmp_path / "profiles.db", RatesClient(tmp_path / "cache.json", fetch=fake_fetch))


def call(server, tool: str, **args) -> str:
    """Chama uma ferramenta pelo cliente MCP em memória e devolve o texto."""

    async def run():
        async with Client(server) as client:
            result = await client.call_tool(tool, args)
            return result.content[0].text

    return asyncio.run(run())


def test_lista_as_nove_ferramentas(server):
    async def run():
        async with Client(server) as client:
            return {tool.name for tool in await client.list_tools()}

    assert asyncio.run(run()) == TOOLS


def test_simulate_installments_formata_reais(server):
    assert "R$ 112,83" in call(server, "simulate_installments", balance=1000, monthly_rate=5, n=12)


def test_simulate_payoff_parcela_insuficiente_vira_erro(server):
    assert call(server, "simulate_payoff", balance=1000, monthly_rate=5, payment=50).startswith("erro:")


def test_simulate_payoff_resultado(server):
    text = call(server, "simulate_payoff", balance=1000, monthly_rate=5, payment=100)
    assert "15 meses" in text
    assert "R$ 421,07" in text


def test_simulate_portability_economia(server):
    text = call(server, "simulate_portability", balance=15000, n_left=36, current_rate=2.1, new_rate=1.81)
    assert "R$ 982,76" in text


def test_market_rate_mostra_mediana_e_data(server):
    text = call(server, "market_rate", modality="cartao_rotativo")
    assert "15,79%" in text
    assert "2026-10-29" in text
    assert "3 bancos" in text


def test_compare_rate_abaixo_da_mediana(server):
    text = call(server, "compare_rate", modality="cartao_rotativo", monthly_rate=14)
    assert "0,89" in text
    assert "abaixo da mediana" in text


def test_compare_rate_modalidade_invalida_lista_validas(server):
    text = call(server, "compare_rate", modality="Cartão rotativo", monthly_rate=14)
    assert text.startswith("erro:")
    assert "cartao_rotativo" in text


def test_market_rate_sem_rede_e_sem_cache(tmp_path):
    offline = build_server(tmp_path / "p.db", RatesClient(tmp_path / "c.json", fetch=offline_fetch))
    assert call(offline, "market_rate", modality="cartao_rotativo").startswith("erro:")


def test_save_debt_idempotente_pelo_servidor(server):
    for _ in range(2):
        call(server, "save_debt", user_id="ana", kind="cartao_rotativo", creditor="Banco Alfa",
             balance=3500, monthly_rate=14)
    profile = json.loads(call(server, "get_profile", user_id="ana"))
    assert len(profile["debts"]) == 2
    rotativo = next(d for d in profile["debts"] if d["kind"] == "cartao_rotativo")
    assert rotativo["balance"] == 3500


def test_save_debt_modalidade_invalida_vira_erro(server):
    text = call(server, "save_debt", user_id="ana", kind="hipoteca", creditor="X", balance=1, monthly_rate=1)
    assert text.startswith("erro:")


def test_remove_debt_de_outro_usuario_pelo_servidor(server):
    ana_debt = json.loads(call(server, "get_profile", user_id="ana"))["debts"][0]["id"]
    assert call(server, "remove_debt", user_id="bruno", debt_id=ana_debt).startswith("erro:")


def test_save_plan_aparece_no_perfil(server):
    call(server, "save_plan", user_id="ana", plan="quitar o rotativo primeiro")
    assert json.loads(call(server, "get_profile", user_id="ana"))["plan"] == "quitar o rotativo primeiro"


def test_get_profile_inexistente_vira_erro(server):
    assert call(server, "get_profile", user_id="zeca").startswith("erro:")


def test_save_plan_usuario_inexistente_vira_erro(server):
    assert call(server, "save_plan", user_id="zeca", plan="x").startswith("erro:")


def test_compare_rate_avisa_quando_usa_cache(tmp_path):
    cache = tmp_path / "c.json"
    RatesClient(cache, fetch=fake_fetch).market_rate("cartao_rotativo")
    offline = build_server(tmp_path / "p.db", RatesClient(cache, fetch=offline_fetch))
    assert "dados em cache" in call(offline, "compare_rate", modality="cartao_rotativo", monthly_rate=14)


def test_simulate_portability_taxa_maior_e_custo(server):
    text = call(server, "simulate_portability", balance=15000, n_left=36, current_rate=1.81, new_rate=2.1)
    assert "custo adicional de R$ 982,76" in text
    assert "economia" not in text
