import re
from pathlib import Path

import pytest

from credito.corpus.parse import html_to_text, split_articles
from credito.corpus.sources import SOURCES

DOCS = Path(__file__).resolve().parent.parent / "data" / "docs"


def test_html_to_text_descarta_texto_riscado():
    assert html_to_text("<p>a <strike>velho</strike> b</p><p>c <s>antigo</s> d</p>") == "a b\n\nc d"


def test_html_to_text_descarta_estilo_line_through_com_span_aninhado():
    raw = (
        '<p><span style="font-size:10pt; text-decoration:line-through">'
        '<a name="art3"></a>Art. 3º velho <span>25%</span> fim</span></p>'
        '<p>Art. 3º novo R$ 600</p>'
    )
    assert html_to_text(raw) == "Art. 3º novo R$ 600"


def test_html_to_text_resolve_entidades():
    assert html_to_text("<p>Art&#58;&nbsp;1</p>") == "Art: 1"


def test_split_articles_rotulos_normalizados():
    text = (
        "Preâmbulo que some.\n"
        "Art. 1° Primeiro.\n"
        "Art. 2º-A Com sufixo.\n"
        "Art. 9 Sem ordinal.\n"
        "Art. 54-G Do CDC.\n"
        "Art. 104-A Repactuação.\n"
    )
    articles = split_articles(text)
    assert [a for a, _ in articles] == ["1º", "2º-A", "9º", "54-G", "104-A"]
    assert articles[0][1] == "Art. 1° Primeiro."
    assert "Preâmbulo" not in "".join(t for _, t in articles)


def test_split_articles_ignora_citacao_no_meio_da_linha():
    articles = split_articles("Art. 5º Conforme o Art. 3º desta lei.\nArt. 6º Outro.")
    assert [a for a, _ in articles] == ["5º", "6º"]


def test_fontes_md_cita_todas_as_fontes():
    fontes = (DOCS / "FONTES.md").read_text()
    for source in SOURCES:
        assert f"`{source.id}`" in fontes
        assert (source.url or source.bcb_number) in fontes


@pytest.mark.parametrize("note", sorted((DOCS / "notas").glob("*.md")), ids=lambda p: p.stem)
def test_notas_tem_frontmatter(note):
    head = note.read_text().split("---")[1]
    assert re.search(r"^title: .+", head, re.M)
    assert "http" in head


def test_existem_as_notas_curadas():
    assert {p.stem for p in (DOCS / "notas").glob("*.md")} == {
        "minimo-existencial-stf", "mp-1355-caducada", "cheque-especial-sem-tarifa", "teto-rotativo-100",
        "rotativo-30-dias", "lei-15252-vigencia", "teto-consignado-inss", "cdc-54e-vetado",
        "portabilidade-fatura",
    }


def test_corpus_baixado_tem_todas_as_fontes():
    for source in SOURCES:
        text = (DOCS / f"{source.id}.txt").read_text()
        assert text.startswith("Art. "), source.id
