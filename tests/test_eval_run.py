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


def test_execute_registra_erro_sem_derrubar(monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager

    from evals.run import execute

    @asynccontextmanager
    async def broken(**kwargs):
        raise RuntimeError("servidor MCP caiu")
        yield

    monkeypatch.setattr("credito.assistant.open_assistant", broken)
    run = asyncio.run(execute(CASE, "gemini-3.5-flash-lite"))
    assert "servidor MCP caiu" in run.error
    assert not score(run, YES)["passed"]


def test_latencia_conta_so_os_turnos(monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage

    from evals.run import execute

    class Graph:
        async def ainvoke(self, state, config):
            return {"messages": [*state["messages"], AIMessage("ok")]}

        async def aget_state(self, config):
            return SimpleNamespace(values={"messages": []})

    @asynccontextmanager
    async def slow_open(**kwargs):
        await asyncio.sleep(0.5)  # abrir servidores MCP e índice não é latência de resposta
        yield SimpleNamespace(graph=Graph(), tools=[])

    monkeypatch.setattr("credito.assistant.open_assistant", slow_open)
    run = asyncio.run(execute(CASE, "gemini-3.5-flash-lite"))
    assert run.error is None
    assert run.seconds < 0.3


def test_observacao_de_caso_nao_julgado():
    from evals.run import observation

    row = {"error": None, "checks_failed": [], "verdict": None, "judged": False, "judge_error": "429"}
    assert observation(row).startswith("não julgado")


def test_mesclar_resultados_substitui_so_os_casos_rodados():
    from evals.run import merge_rows

    old = [{"id": 1, "passed": True}, {"id": 7, "passed": False}]
    assert merge_rows(old, [{"id": 7, "passed": True}]) == [{"id": 1, "passed": True}, {"id": 7, "passed": True}]
