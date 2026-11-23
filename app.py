"""Interface do assistente de dívidas e crédito.

    uv run streamlit run app.py

O assistente (grafo, servidores MCP e checkpointer) fica aberto numa thread de
fundo (credito/runner.py); a tela é redesenhada a cada interação a partir do
checkpointer, como no app de notas fiscais do professor.
"""

import os
import uuid
from pathlib import Path

import streamlit as st

from credito import rates, runner
from credito.calc import brl
from credito.graph import BLOCKED_PLACEHOLDER
from credito.profiles import ProfileStore
from credito.ui import panel_rows, turns

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("CREDITO_DB", ROOT / "data" / "profiles.db"))


# st.cache_resource guarda o objeto entre as reexecuções: o assistente e os
# servidores MCP são abertos uma vez só, e fechados quando o cache é descartado.
@st.cache_resource(on_release=lambda assistant: assistant.close())
def get_runner():
    return runner.AssistantRunner()


@st.cache_data(ttl=3600, show_spinner=False)
def median_for(kind: str) -> float | None:
    """Mediana do mercado para a modalidade (BCB, com cache local); None se não houver dado."""
    try:
        return rates.RatesClient(ROOT / "data" / "rates_cache.json").market_rate(kind).median
    except Exception:  # sem rede e sem cache o painel segue sem a comparação
        return None


st.set_page_config(page_title="Assistente de dívidas", page_icon="💳", layout="wide")
store = ProfileStore(DB)
store.seed()
users = dict(store.users())  # id -> nome

# st.session_state sobrevive às reexecuções: guarda uma thread por usuário,
# porque cada conversa é presa ao usuário que a começou.
if "threads" not in st.session_state:
    st.session_state.threads = {}

with st.sidebar:
    name = st.selectbox("Usuário", list(users.values()), key="user_name")
    user_id = next(uid for uid, uname in users.items() if uname == name)
    if st.button("Nova conversa") or user_id not in st.session_state.threads:
        st.session_state.threads[user_id] = str(uuid.uuid4())
    thread_id = st.session_state.threads[user_id]

    profile = store.get_profile(user_id)
    st.subheader("Perfil")
    left, right = st.columns(2)
    left.metric("Renda", brl(profile["income"]))
    right.metric("Total devido", brl(profile["total_balance"]))
    for row in panel_rows(profile, median_for):
        flag = "🔴" if row.above_market else "🟢" if row.above_market is False else "⚪"
        market = f" · {row.market}" if row.market else ""
        st.markdown(f"{flag} **{row.creditor}** — {row.kind}  \n{row.balance} a {row.rate} a.m.{market}")
    if profile["plan"]:
        with st.expander("Plano salvo"):
            st.markdown(profile["plan"])
    st.caption(f"Conversa {thread_id[:8]}")

st.title("Assistente de dívidas e crédito")
st.caption("Compara seus juros com o mercado (Banco Central), simula quitação e portabilidade e explica seus direitos.")

assistant = get_runner()
try:
    history = turns(assistant.history(thread_id))
except Exception as error:
    history = []
    st.error(f"Não consegui abrir o assistente: {error}")
    if assistant.error is not None:
        get_runner.clear()  # a próxima interação tenta abrir de novo, em vez de repetir o erro

for turn in history:
    st.chat_message("user").markdown(
        f"_{turn.question}_" if turn.question == BLOCKED_PLACEHOLDER else turn.question
    )
    with st.chat_message("assistant"):
        if turn.tools or turn.skills:
            label = f"{len(turn.tools)} ferramenta(s)" + (f" · skill: {', '.join(turn.skills)}" if turn.skills else "")
            with st.expander(label):
                for tool in turn.tools:
                    st.markdown(f"- `{tool}`")
                for skill in turn.skills:
                    st.markdown(f"- skill `{skill}`")
        st.markdown(turn.answer or "_(sem resposta: o turno foi interrompido; tente perguntar de novo)_")

if question := st.chat_input("Pergunte sobre suas dívidas, juros ou direitos"):
    st.chat_message("user").markdown(question)
    with st.spinner("Pensando..."):
        try:
            assistant.ask(user_id, thread_id, question)
        except Exception as error:
            st.error(f"Não consegui responder agora: {error}")
        else:
            st.rerun()
