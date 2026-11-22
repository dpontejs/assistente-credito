"""Lógica da interface sem Streamlit: turnos da conversa e linhas do painel do perfil."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from credito.calc import brl
from credito.graph import as_text

KIND_NAMES = {
    "cartao_rotativo": "Cartão (rotativo)",
    "cartao_parcelado": "Cartão (parcelado)",
    "cheque_especial": "Cheque especial",
    "pessoal": "Empréstimo pessoal",
    "consignado_inss": "Consignado INSS",
    "consignado_privado": "Consignado privado",
    "consignado_publico": "Consignado público",
    "veiculo": "Financiamento de veículo",
}


@dataclass
class Turn:
    question: str
    answer: str = ""
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


@dataclass
class PanelRow:
    creditor: str
    kind: str
    balance: str
    rate: str
    market: str | None
    above_market: bool | None


def pct(value: float) -> str:
    return f"{value:.2f}%".replace(".", ",")


def turns(messages: list[BaseMessage]) -> list[Turn]:
    """Agrupa as mensagens em turnos: pergunta, resposta final, ferramentas e skills usadas."""
    result: list[Turn] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            result.append(Turn(question=as_text(message.content)))
        elif isinstance(message, AIMessage) and result:
            turn = result[-1]
            for call in message.tool_calls:
                if call["name"] == "load_skill":
                    turn.skills.append(call["args"].get("name", ""))
                else:
                    turn.tools.append(call["name"])
            if not message.tool_calls:
                turn.answer = as_text(message.content)
    return result


def panel_rows(profile: dict, median_for: Callable[[str], float | None]) -> list[PanelRow]:
    """Linhas do painel: cada dívida com saldo, taxa e posição em relação à mediana do mercado."""
    rows = []
    for debt in profile.get("debts", []):
        median = median_for(debt["kind"])
        above = None if median is None else debt["monthly_rate"] > median
        market = None
        if median is not None:
            market = f"{'acima' if above else 'abaixo'} da mediana ({pct(median)})"
        rows.append(PanelRow(
            creditor=debt["creditor"],
            kind=KIND_NAMES.get(debt["kind"], debt["kind"]),
            balance=brl(debt["balance"]),
            rate=pct(debt["monthly_rate"]),
            market=market,
            above_market=above,
        ))
    return rows
