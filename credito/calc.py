"""Calculadoras de crédito: Tabela Price, quitação e portabilidade.

Todas as taxas estão em % ao mês (5.0 = 5% a.m.), como na API do BCB.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_MONTHS = 600


@dataclass(frozen=True)
class Payoff:
    months: int
    total_interest: float


@dataclass(frozen=True)
class Portability:
    current_installment: float
    new_installment: float
    total_savings: float


def _check_positive(**values: float) -> None:
    """Recusa saldo, prazo ou parcela que não sejam positivos."""
    for name, value in values.items():
        if value <= 0:
            raise ValueError(f"{name} precisa ser maior que zero")


def _check_rate(rate: float) -> None:
    """Recusa taxa negativa."""
    if rate < 0:
        raise ValueError("a taxa não pode ser negativa")


def price_installment(balance: float, monthly_rate: float, n: int) -> float:
    """Calcula a parcela fixa pela Tabela Price."""
    _check_positive(saldo=balance, prazo=n)
    _check_rate(monthly_rate)
    rate = monthly_rate / 100
    if rate == 0:
        return balance / n
    return balance * rate / (1 - (1 + rate) ** -n)


def payoff(balance: float, monthly_rate: float, payment: float) -> Payoff:
    """Simula mês a mês quanto tempo e quanto de juros leva para quitar com uma parcela fixa."""
    _check_positive(saldo=balance, parcela=payment)
    _check_rate(monthly_rate)
    rate = monthly_rate / 100
    if payment <= balance * rate:
        raise ValueError("a parcela não cobre os juros do mês; a dívida nunca seria quitada")
    months, total_interest = 0, 0.0
    while balance > 1e-9:
        if months >= MAX_MONTHS:
            raise ValueError(f"a quitação levaria mais de {MAX_MONTHS} meses")
        interest = balance * rate
        total_interest += interest
        balance -= min(payment, balance + interest) - interest
        months += 1
    return Payoff(months=months, total_interest=total_interest)


def portability(balance: float, n_left: int, current_rate: float, new_rate: float) -> Portability:
    """Compara a parcela atual com a de uma nova taxa no mesmo prazo restante."""
    current = price_installment(balance, current_rate, n_left)
    new = price_installment(balance, new_rate, n_left)
    return Portability(current, new, (current - new) * n_left)


def brl(value: float) -> str:
    """Formata um valor em reais no padrão brasileiro."""
    text = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {text}"
