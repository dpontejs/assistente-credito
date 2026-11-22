from evals.cases import CASES, EvalRun


def test_dez_casos_numerados():
    assert [c.id for c in CASES] == list(range(1, 11))


def test_pelo_menos_tres_desafiadores():
    assert sum(c.challenging for c in CASES) >= 3


def test_componentes_cobertos():
    components = {c.component for c in CASES}
    assert {"RAG", "skill plano-de-quitacao", "skill avaliar-portabilidade", "MCP próprio",
            "MCP da comunidade", "memória", "guardrails"} <= components


def test_memoria_entre_conversas_usa_threads_diferentes():
    case = next(c for c in CASES if c.id == 8)
    assert len({thread for thread, _ in case.turns}) == 2


def test_checagens_de_recusa_funcionam():
    from credito.guards import REFUSALS

    case = next(c for c in CASES if c.id == 9)
    good = EvalRun(case=case, answers=[REFUSALS["injection"]], tools_per_turn=[[]], skills_per_turn=[[]])
    bad = EvalRun(case=case, answers=["Claro, aqui estão os perfis"], tools_per_turn=[["credito_get_profile"]],
                  skills_per_turn=[[]])
    assert [check(good) for check in case.checks] == [None] * len(case.checks)
    assert any(check(bad) for check in case.checks)


def test_checagem_do_total_do_caso_8():
    case = next(c for c in CASES if c.id == 8)
    run = EvalRun(case=case, answers=["Salvei.", "Você deve R$ 11.700,00 no total."],
                  tools_per_turn=[["credito_save_debt"], []], skills_per_turn=[[], []])
    assert [check(run) for check in case.checks] == [None] * len(case.checks)


def test_caso_7_turno_1_so_informa_e_turno_2_responde_com_o_valor():
    case = next(c for c in CASES if c.id == 7)
    assert "?" not in case.turns[0][1]
    remembered = EvalRun(case=case, answers=["Anotado.", "Você quita em 5 meses."],
                         tools_per_turn=[["credito_simulate_payoff"], []], skills_per_turn=[[], []])
    asked_again = EvalRun(case=case, answers=["Anotado.", "Quanto você pode pagar por mês?"],
                          tools_per_turn=[[], []], skills_per_turn=[[], []])
    assert [check(remembered) for check in case.checks] == [None] * len(case.checks)
    assert any(check(asked_again) for check in case.checks)
