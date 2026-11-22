from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from streamlit.testing.v1 import AppTest

from credito.profiles import ProfileStore

APP = str(Path(__file__).resolve().parent.parent / "app.py")


class FakeRunner:
    instances: list = []

    def __init__(self, *args, **kwargs):
        self.asked: list[tuple] = []
        self.threads: dict[str, list] = {}
        self.fail: Exception | None = None
        FakeRunner.instances.append(self)

    def ask(self, user_id, thread_id, text):
        if self.fail:
            raise self.fail
        self.asked.append((user_id, thread_id, text))
        call = {"name": "credito_get_profile", "args": {"user_id": "atual"}, "id": "c1"}
        self.threads.setdefault(thread_id, []).extend(
            [HumanMessage(text), AIMessage("", tool_calls=[call]), AIMessage("Você deve R$ 19.000,00.")]
        )
        return self.threads[thread_id]

    def history(self, thread_id):
        return list(self.threads.get(thread_id, []))


class FakeRates:
    def __init__(self, *args, **kwargs):
        pass

    def market_rate(self, kind):
        return SimpleNamespace(median=15.79)


@pytest.fixture
def app(tmp_path, monkeypatch):
    import streamlit as st

    db = tmp_path / "profiles.db"
    ProfileStore(db).seed()
    monkeypatch.setenv("CREDITO_DB", str(db))
    monkeypatch.setattr("credito.runner.AssistantRunner", FakeRunner)
    monkeypatch.setattr("credito.rates.RatesClient", FakeRates)
    FakeRunner.instances.clear()
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def test_barra_lateral_tem_usuarios_e_nova_conversa(app):
    assert not app.exception
    assert app.sidebar.selectbox[0].options == ["Ana Souza", "Bruno Lima", "Carla Mendes"]
    assert app.sidebar.button[0].label == "Nova conversa"


def test_painel_mostra_renda_e_total_da_ana(app):
    text = " ".join(m.value for m in app.sidebar.markdown) + " ".join(str(m.value) for m in app.sidebar.metric)
    assert "R$ 4.500,00" in text
    assert "R$ 19.000,00" in text


def test_pergunta_vai_para_o_runner_e_resposta_aparece_com_ferramentas(app):
    app.chat_input[0].set_value("quanto eu devo?").run()
    runner = FakeRunner.instances[-1]
    user, thread, text = runner.asked[0]
    assert (user, text) == ("ana", "quanto eu devo?")
    assert thread == app.session_state.threads["ana"]
    assert any("R$ 19.000,00" in m.value for m in app.markdown)
    assert any("credito_get_profile" in e.label or any("credito_get_profile" in m.value for m in e.markdown)
               for e in app.expander)


def test_nova_conversa_troca_a_thread(app):
    before = app.session_state.threads["ana"]
    app.sidebar.button[0].click().run()
    assert app.session_state.threads["ana"] != before


def test_trocar_de_usuario_usa_outra_thread(app):
    ana = app.session_state.threads["ana"]
    app.sidebar.selectbox[0].select("Bruno Lima").run()
    app.chat_input[0].set_value("oi").run()
    user, thread, _ = FakeRunner.instances[-1].asked[-1]
    assert user == "bruno" and thread != ana


def test_erro_do_assistente_vira_aviso(app):
    FakeRunner.instances[-1].fail = RuntimeError("429 RESOURCE_EXHAUSTED")
    app.chat_input[0].set_value("oi").run()
    assert not app.exception
    assert "429" in app.error[0].value
