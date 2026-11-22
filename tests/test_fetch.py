import json

import pytest

from credito.corpus.fetch import FetchError, fetch_source, latest_consolidated_pdf
from credito.corpus.sources import SOURCES, Source

BCB_OLD = Source(id="res9", label="Res. 9", title="t", kind="bcb", bcb_type="Resolução", bcb_number="9")
PLANALTO = Source(id="lei1", label="Lei 1", title="t", kind="planalto", url="https://planalto/l1.htm")


def bcb_json(**fields) -> bytes:
    item = {"Id": "123", "Revogado": "False", "Documentos": None, "Texto": "<p>Art. 1º Texto.</p>",
            "Atualizacoes": None, **fields}
    return json.dumps({"conteudo": [item]}).encode()


def fake_get(responses: dict[str, bytes]):
    """Devolve um get que responde pelo trecho da URL e registra as chamadas."""
    calls = []

    def get(url: str) -> bytes:
        calls.append(url)
        for fragment, body in responses.items():
            if fragment in url:
                return body
        raise AssertionError(f"URL inesperada: {url}")

    get.calls = calls
    return get


def test_latest_consolidated_pdf_pega_maior_versao():
    docs = "Res_3919_v1_O.pdf;190#;Res_3919_v2_L.pdf;246#;Res_3919_v7_L.pdf;300#;Res_3919_v7_P.pdf;301#;"
    assert latest_consolidated_pdf(docs) == "Res_3919_v7_L.pdf"


def test_latest_consolidated_pdf_sem_consolidado():
    assert latest_consolidated_pdf("Res_1_v1_O.pdf;1#;") is None
    assert latest_consolidated_pdf(None) is None


def test_bcb_conteudo_vazio_falha_com_dica_do_tipo():
    get = fake_get({"exibenormativo": json.dumps({"conteudo": []}).encode()})
    with pytest.raises(FetchError, match="tipo"):
        fetch_source(BCB_OLD, get=get)


def test_bcb_revogada_falha():
    get = fake_get({"exibenormativo": bcb_json(Revogado="True")})
    with pytest.raises(FetchError, match="revogad"):
        fetch_source(BCB_OLD, get=get)


def test_bcb_sem_pdf_usa_texto_da_api():
    text, meta = fetch_source(BCB_OLD, get=fake_get({"exibenormativo": bcb_json()}))
    assert "Art. 1º Texto." in text
    assert meta["revogado"] is False
    assert meta["arquivo"] is None


def test_bcb_com_consolidado_baixa_o_pdf(monkeypatch):
    monkeypatch.setattr("credito.corpus.fetch.pdf_to_text", lambda data: data.decode())
    get = fake_get({
        "exibenormativo": bcb_json(Documentos="Res_9_v1_O.pdf;1#;Res_9_v2_L.pdf;2#;"),
        "Attachments/123/Res_9_v2_L.pdf": b"Art. 1o consolidado",
    })
    text, meta = fetch_source(BCB_OLD, get=get)
    assert text == "Art. 1o consolidado"
    assert meta["arquivo"] == "Res_9_v2_L.pdf"
    assert get.calls[-1] == "https://normativos.bcb.gov.br/Lists/Normativos/Attachments/123/Res_9_v2_L.pdf"


def test_planalto_decodifica_cp1252():
    html, meta = fetch_source(PLANALTO, get=fake_get({"l1.htm": "<p>Incluído</p>".encode("cp1252")}))
    assert "Incluído" in html
    assert meta["url"] == "https://planalto/l1.htm"


def test_nucleo_tem_as_onze_fontes():
    assert [s.id for s in SOURCES] == [
        "cdc", "dec11150", "lei14690", "lei10820", "res4549", "bcb96",
        "cmn4882", "res4765", "cmn5057", "res3919", "cmn4881",
    ]


@pytest.mark.network
def test_planalto_e_bcb_reais():
    by_id = {s.id: s for s in SOURCES}
    cdc, _ = fetch_source(by_id["cdc"])
    assert "Art. 54-A" in cdc
    cmn, _ = fetch_source(by_id["cmn4882"])
    assert "Art. 1º" in cmn
