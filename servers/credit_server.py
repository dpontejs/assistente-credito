"""Servidor MCP de crédito: calculadoras, taxas de mercado do BCB e perfil do usuário.

    uv run python servers/credit_server.py

Roda em stdio. Constrói os próprios recursos (banco e cache), porque roda em
outro processo e não enxerga as variáveis do agente.
"""

from __future__ import annotations

import json
import os
from functools import wraps
from pathlib import Path

# antes do import: o cliente stdio não repassa o ambiente ao servidor
os.environ.setdefault("FASTMCP_LOG_LEVEL", "WARNING")

from fastmcp import FastMCP  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from credito.calc import brl, payoff, portability, price_installment  # noqa: E402
from credito.profiles import Debt, ProfileStore  # noqa: E402
from credito.rates import MODALITIES, RatesClient, RatesUnavailable  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VALID = ", ".join(MODALITIES)


def pct(value: float) -> str:
    """Formata uma taxa em % com vírgula decimal."""
    return f"{value:.2f}%".replace(".", ",")


def origin(rate) -> str:
    """Diz de quando é o dado e se veio do cache."""
    if rate.from_cache:
        return f"dados em cache de {rate.period_start}"
    return f"semana iniciada em {rate.period_start}"


def as_error(func):
    """Transforma erros de entrada ou de rede em texto 'erro: ...' para o modelo."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except KeyError as error:
            return f"erro: modalidade {error} desconhecida; use uma destas: {VALID}"
        except ValidationError as error:
            fields = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
            return f"erro: dados inválidos ({fields}); modalidades válidas: {VALID}"
        except (ValueError, RatesUnavailable) as error:
            return f"erro: {error}"

    return wrapper


def db_path() -> Path:
    """Banco de perfis: CREDITO_DB, se definido (a avaliação usa um banco temporário), senão data/profiles.db."""
    return Path(os.environ.get("CREDITO_DB", ROOT / "data" / "profiles.db"))


def build_server(db_path: Path, rates: RatesClient) -> FastMCP:
    """Monta o servidor com o banco de perfis e o cliente de taxas informados."""
    store = ProfileStore(db_path)
    store.seed()
    mcp = FastMCP("credito")

    @mcp.tool()
    @as_error
    def market_rate(modality: str) -> str:
        """Mediana da taxa de juros (% ao mês) que os bancos cobram na modalidade, segundo o BCB. Modalidades: cartao_rotativo, cartao_parcelado, cheque_especial, pessoal, consignado_inss, consignado_privado, consignado_publico, veiculo."""
        rate = rates.market_rate(modality)
        return (
            f"{modality}: mediana de {pct(rate.median)} ao mês entre {rate.n_institutions} bancos "
            f"(BCB, {origin(rate)})."
        )

    @mcp.tool()
    @as_error
    def compare_rate(modality: str, monthly_rate: float) -> str:
        """Compara a taxa do cliente (% ao mês) com a mediana do mercado na modalidade, segundo o BCB."""
        rate = rates.market_rate(modality)
        ratio = monthly_rate / rate.median
        position = "acima da mediana" if ratio > 1 else "abaixo da mediana" if ratio < 1 else "igual à mediana"
        return (
            f"A taxa de {pct(monthly_rate)} ao mês é {f'{ratio:.2f}'.replace('.', ',')} vez a mediana de "
            f"{pct(rate.median)} ({rate.n_institutions} bancos, BCB, {origin(rate)}): {position}."
        )

    @mcp.tool()
    @as_error
    def simulate_payoff(balance: float, monthly_rate: float, payment: float) -> str:
        """Simula em quantos meses e com quanto de juros uma dívida (R$, % ao mês) é quitada pagando uma parcela fixa (R$)."""
        result = payoff(balance, monthly_rate, payment)
        return (
            f"Pagando {brl(payment)} por mês, a dívida de {brl(balance)} a {pct(monthly_rate)} ao mês "
            f"é quitada em {result.months} meses, com {brl(result.total_interest)} de juros."
        )

    @mcp.tool()
    @as_error
    def simulate_installments(balance: float, monthly_rate: float, n: int) -> str:
        """Calcula a parcela pela Tabela Price para parcelar um saldo (R$) a uma taxa (% ao mês) em n meses."""
        installment = price_installment(balance, monthly_rate, n)
        return (
            f"{brl(balance)} em {n}x a {pct(monthly_rate)} ao mês: parcela de {brl(installment)}, "
            f"total de {brl(installment * n)}."
        )

    @mcp.tool()
    @as_error
    def simulate_portability(balance: float, n_left: int, current_rate: float, new_rate: float) -> str:
        """Compara a parcela atual com a de uma nova taxa (% ao mês) no mesmo prazo restante, para avaliar portabilidade."""
        result = portability(balance, n_left, current_rate, new_rate)
        if result.total_savings >= 0:
            verdict = f"economia total de {brl(result.total_savings)}"
        else:
            verdict = f"custo adicional de {brl(-result.total_savings)}; portar não compensa"
        return (
            f"Parcela atual {brl(result.current_installment)} ({pct(current_rate)}) contra "
            f"{brl(result.new_installment)} ({pct(new_rate)}) em {n_left} meses: {verdict}."
        )

    @mcp.tool()
    @as_error
    def get_profile(user_id: str) -> str:
        """Devolve em JSON a renda, as dívidas e o plano mais recente do usuário."""
        profile = store.get_profile(user_id)
        if profile is None:
            raise ValueError(f"usuário {user_id} não existe")
        return json.dumps(profile, ensure_ascii=False)

    @mcp.tool()
    @as_error
    def save_debt(
        user_id: str,
        kind: str,
        creditor: str,
        balance: float,
        monthly_rate: float,
        installments_left: int | None = None,
    ) -> str:
        """Salva no perfil uma dívida (saldo em R$, taxa em % ao mês); a mesma modalidade e credor é atualizada, não duplicada."""
        debt = Debt(
            kind=kind, creditor=creditor, balance=balance,
            monthly_rate=monthly_rate, installments_left=installments_left,
        )
        debt_id = store.save_debt(user_id, debt)
        return f"dívida {debt_id} salva: {kind} com {creditor}, {brl(balance)} a {pct(monthly_rate)} ao mês."

    @mcp.tool()
    @as_error
    def remove_debt(user_id: str, debt_id: int) -> str:
        """Remove do perfil uma dívida do usuário pelo id."""
        if not store.remove_debt(user_id, debt_id):
            raise ValueError(f"dívida {debt_id} não encontrada no perfil de {user_id}")
        return f"dívida {debt_id} removida."

    @mcp.tool()
    @as_error
    def save_plan(user_id: str, plan: str) -> str:
        """Guarda o plano de quitação do usuário; o mais recente substitui os anteriores."""
        store.save_plan(user_id, plan)
        return "plano salvo."

    return mcp


if __name__ == "__main__":
    server = build_server(db_path(), RatesClient(ROOT / "data" / "rates_cache.json"))
    server.run(show_banner=False)
