import re

from credito.guards import REFUSALS, SAFE_OUTPUT, mask_sensitive


def test_mascara_cpf_e_cartao():
    masked = mask_sensitive("Meu CPF é 123.456.789-09 e o cartão 4111 1111 1111 1111, ok?")
    assert "[CPF removido]" in masked
    assert "[cartão removido]" in masked
    assert not re.search(r"\d{3}\.\d{3}|4111", masked)


def test_mascara_cpf_sem_pontuacao_e_cartao_com_hifen():
    masked = mask_sensitive("cpf 12345678909 cartao 5500-0000-0000-0004")
    assert masked == "cpf [CPF removido] cartao [cartão removido]"


def test_texto_sem_dados_fica_igual():
    text = "Devo R$ 4.000,00 a 14% ao mês desde 12/03/2026, 36 parcelas."
    assert mask_sensitive(text) == text


def test_recusas_por_categoria():
    assert set(REFUSALS) == {"injection", "fora_do_escopo", "dados_de_terceiros"}
    assert all(REFUSALS.values()) and SAFE_OUTPUT
