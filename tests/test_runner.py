from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from credito.runner import AssistantRunner


class FakeGraph:
    def __init__(self):
        self.threads: dict[str, list] = {}

    async def ainvoke(self, state, config):
        thread = self.threads.setdefault(config["configurable"]["thread_id"], [])
        thread += [*state["messages"], AIMessage(f"resposta para {state['user_id']}")]
        return {"messages": list(thread)}

    async def aget_state(self, config):
        return SimpleNamespace(values={"messages": list(self.threads.get(config["configurable"]["thread_id"], []))})


def fake_factory(log: list):
    @asynccontextmanager
    async def factory():
        log.append("abriu")
        yield SimpleNamespace(graph=FakeGraph(), tools=[])
        log.append("fechou")

    return factory


def test_ask_devolve_as_mensagens_da_thread():
    log = []
    runner = AssistantRunner(fake_factory(log))
    messages = runner.ask("ana", "t1", "quanto eu devo?")
    assert isinstance(messages[0], HumanMessage)
    assert messages[-1].content == "resposta para ana"
    assert runner.history("t1") == messages
    runner.close()


def test_abre_uma_vez_e_fecha_no_close():
    log = []
    runner = AssistantRunner(fake_factory(log))
    runner.ask("ana", "t1", "a")
    runner.ask("ana", "t1", "b")
    assert log == ["abriu"]
    runner.close()
    assert log == ["abriu", "fechou"]


def test_historico_de_thread_nova_e_vazio():
    runner = AssistantRunner(fake_factory([]))
    assert runner.history("nova") == []
    runner.close()


def test_erro_ao_abrir_aparece_no_ask():
    @asynccontextmanager
    async def broken():
        raise RuntimeError("GOOGLE_API_KEY ausente")
        yield

    runner = AssistantRunner(broken)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        runner.ask("ana", "t1", "oi")
    runner.close()


def slow_factory(state: dict):
    class SlowGraph(FakeGraph):
        async def ainvoke(self, input, config):
            import asyncio

            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise
            state["finished"] = True
            return {"messages": []}

    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(graph=SlowGraph(), tools=[])

    return factory


def test_ask_que_estoura_o_tempo_e_cancelado_com_mensagem_clara():
    import time

    state = {}
    runner = AssistantRunner(slow_factory(state), timeout=0.3)
    with pytest.raises(TimeoutError, match="demorou"):
        runner.ask("ana", "t1", "oi")
    time.sleep(0.3)
    assert state.get("cancelled") is True
    assert "finished" not in state
    runner.close()


def test_abertura_lenta_da_erro_claro():
    import asyncio

    @asynccontextmanager
    async def opening_forever():
        await asyncio.sleep(10)
        yield

    runner = AssistantRunner(opening_forever, timeout=0.2)
    with pytest.raises(TimeoutError, match="abrindo"):
        runner.ask("ana", "t1", "oi")


def test_runner_expoe_erro_de_abertura():
    @asynccontextmanager
    async def broken():
        raise RuntimeError("429 ao indexar")
        yield

    runner = AssistantRunner(broken)
    with pytest.raises(RuntimeError):
        runner.history("t1")
    assert isinstance(runner.error, RuntimeError)
