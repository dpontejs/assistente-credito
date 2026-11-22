import pytest

from credito.calc import Payoff, brl, payoff, portability, price_installment


def test_price_installment_tabela_price():
    assert round(price_installment(1000, 5, 12), 2) == 112.83


def test_price_installment_taxa_zero():
    assert price_installment(1200, 0, 12) == 100.0


@pytest.mark.parametrize("balance, n", [(1000, 0), (-1, 12), (0, 12)])
def test_price_installment_entrada_invalida(balance, n):
    with pytest.raises(ValueError):
        price_installment(balance, 5, n)


def test_payoff_meses_e_juros():
    result = payoff(1000, 5, 100)
    assert result == Payoff(months=15, total_interest=pytest.approx(421.07, abs=0.01))


def test_payoff_parcela_menor_que_juros():
    with pytest.raises(ValueError, match="não cobre os juros"):
        payoff(1000, 5, 50)


def test_portability_economia():
    p = portability(15000, 36, 2.1, 1.81)
    assert round(p.current_installment, 2) == 597.99
    assert round(p.new_installment, 2) == 570.69
    assert round(p.total_savings, 2) == 982.76


def test_brl_formato_brasileiro():
    assert brl(1234.5) == "R$ 1.234,50"
    assert brl(0.5) == "R$ 0,50"
