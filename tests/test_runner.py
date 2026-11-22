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
