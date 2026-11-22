from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from credito.graph import BLOCKED_PLACEHOLDER
from credito.rates import MODALITIES
from credito.ui import KIND_NAMES, panel_rows, turns


def tool_call(tool_name, **args):
    return {"name": tool_name, "args": args, "id": f"id-{tool_name}"}


def test_turnos_com_ferramentas_e_skills():
    messages = [
        HumanMessage("monte um plano"),
        AIMessage("", tool_calls=[tool_call("load_skill", name="plano-de-quitacao")]),
        ToolMessage("instruções", tool_call_id="id-load_skill"),
        AIMessage("", tool_calls=[tool_call("credito_compare_rate", modality="pessoal", monthly_rate=6),
                                  tool_call("search_norms", query="x")]),
        ToolMessage("abaixo", tool_call_id="id-credito_compare_rate"),
        ToolMessage("[CDC art. 54-A]", tool_call_id="id-search_norms"),
        AIMessage("Aqui está o plano."),
        HumanMessage("obrigado"),
        AIMessage("De nada!"),
    ]
    first, second = turns(messages)
    assert first.question == "monte um plano"
    assert first.answer == "Aqui está o plano."
    assert first.tools == ["credito_compare_rate", "search_norms"]
    assert first.skills == ["plano-de-quitacao"]
    assert (second.answer, second.tools, second.skills) == ("De nada!", [], [])


def test_turno_recusado():
    (turn,) = turns([HumanMessage(BLOCKED_PLACEHOLDER), AIMessage("Não posso.")])
    assert turn.question == BLOCKED_PLACEHOLDER
    assert (turn.answer, turn.tools) == ("Não posso.", [])


def test_resposta_em_blocos_vira_texto():
    (turn,) = turns([HumanMessage("oi"), AIMessage([{"type": "text", "text": "olá"}])])
    assert turn.answer == "olá"


def test_turno_sem_resposta():
    (turn,) = turns([HumanMessage("oi")])
    assert turn.answer == ""


PROFILE = {"income": 4500, "debts": [
    {"id": 1, "kind": "cartao_rotativo", "creditor": "Banco Alfa", "balance": 4000, "monthly_rate": 14.0,
     "installments_left": None},
    {"id": 2, "kind": "pessoal", "creditor": "Financeira Zeta", "balance": 5000, "monthly_rate": 6.0,
     "installments_left": 20},
]}


def test_painel_compara_com_a_mediana():
    medians = {"cartao_rotativo": 15.79, "pessoal": 5.8}
    rotativo, pessoal = panel_rows(PROFILE, medians.get)
    assert (rotativo.creditor, rotativo.kind) == ("Banco Alfa", "Cartão (rotativo)")
    assert (rotativo.balance, rotativo.rate) == ("R$ 4.000,00", "14,00%")
    assert rotativo.above_market is False
    assert rotativo.market == "abaixo da mediana (15,79%)"
    assert pessoal.above_market is True


def test_painel_sem_mediana():
    rows = panel_rows(PROFILE, lambda kind: None)
    assert all(row.market is None and row.above_market is None for row in rows)


def test_nomes_cobrem_todas_as_modalidades():
    assert set(KIND_NAMES) == set(MODALITIES)
