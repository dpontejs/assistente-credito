import pytest

from evals.cases import CASES, EvalRun
from evals.run import Verdict, cost_usd, score

CASE = next(c for c in CASES if c.id == 3)  # exige credito_compare_rate e "15," na resposta
GOOD = dict(answers=["Está abaixo da mediana de 15,8%."], tools_per_turn=[["credito_compare_rate"]],
            skills_per_turn=[[]])
YES = Verdict(correct=True, reason="ok")


def test_custo_por_modelo():
    assert cost_usd("gemini-3.5-flash-lite", 1_000_000, 1_000_000) == pytest.approx(2.80)
    assert cost_usd("gemini-3.6-flash", 2_000_000, 0) == pytest.approx(1.50)


def test_aprova_com_tudo_certo():
    result = score(EvalRun(case=CASE, **GOOD), YES)
    assert result["passed"] and result["tools_ok"] and result["judged"]


def test_reprova_sem_a_ferramenta_esperada():
    result = score(EvalRun(case=CASE, **{**GOOD, "tools_per_turn": [["search_norms"]]}), YES)
    assert not result["passed"] and not result["tools_ok"]


def test_reprova_quando_checagem_falha():
    result = score(EvalRun(case=CASE, **{**GOOD, "answers": ["Está ótima."]}), YES)
    assert not result["passed"]
    assert result["checks_failed"]


def test_reprova_quando_o_juiz_reprova():
    assert not score(EvalRun(case=CASE, **GOOD), Verdict(correct=False, reason="errou"))["passed"]


def test_sem_juiz_nao_aprova():
    result = score(EvalRun(case=CASE, **GOOD), None)
    assert not result["passed"] and not result["judged"]


def test_erro_reprova():
    result = score(EvalRun(case=CASE, **GOOD, error="TimeoutError"), YES)
    assert not result["passed"]


def test_skill_esperada():
    case = next(c for c in CASES if c.id == 5)
    run = EvalRun(case=case, answers=["plano"], tools_per_turn=[["credito_simulate_payoff"]], skills_per_turn=[[]])
    assert not score(run, YES)["tools_ok"]
