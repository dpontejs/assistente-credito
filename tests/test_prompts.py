from credito.prompts import system_prompt

PROFILE = '{"id": "ana", "debts": [{"kind": "cartao_rotativo", "balance": 4000}]}'
CATALOG = "- plano-de-quitacao: Monta um plano."


def test_prompt_tem_perfil_e_catalogo():
    prompt = system_prompt(PROFILE, CATALOG, retry_query=None, search_exhausted=False)
    assert PROFILE in prompt
    assert CATALOG in prompt
    assert "busque de novo" not in prompt.lower()
    assert "não encontrou" not in prompt


def test_prompt_com_reescrita_pede_nova_busca():
    prompt = system_prompt(PROFILE, CATALOG, retry_query="portabilidade de crédito prazos", search_exhausted=False)
    assert "portabilidade de crédito prazos" in prompt
    assert "search_norms" in prompt


def test_prompt_com_busca_esgotada():
    assert "não encontrou" in system_prompt(PROFILE, CATALOG, retry_query=None, search_exhausted=True)
