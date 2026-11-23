import re
import json

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from credito.rag import (
    GradeDocuments,
    build_vector_store,
    grade_chunks,
    load_chunks,
    make_search_tool,
    rewrite_query,
)

LONG_ARTICLE = "Art. 54-A Este Capítulo dispõe sobre superendividamento. " + "Texto do parágrafo. " * 130


@pytest.fixture
def docs_dir(tmp_path):
    docs = tmp_path / "docs"
    (docs / "notas").mkdir(parents=True)
    (docs / "cdc.txt").write_text(f"{LONG_ARTICLE}\n\nArt. 54-B O fornecedor deve informar o custo efetivo total.\n")
    (docs / "cdc.json").write_text(json.dumps({"id": "cdc", "label": "CDC", "url": "https://planalto/cdc"}))
    (docs / "notas" / "teto.md").write_text(
        "---\ntitle: Teto do rotativo\nsources:\n  - https://exemplo\n---\nO teto é de 100% do valor original.\n"
    )
    return docs


@pytest.fixture
def store(docs_dir, tmp_path):
    return build_vector_store(docs_dir, tmp_path / "chroma", DeterministicFakeEmbedding(size=32))


def test_cada_trecho_comeca_com_rotulo(docs_dir):
    chunks = [c for c in load_chunks(docs_dir) if c.metadata["article"] == "54-A"]
    assert len(chunks) >= 3
    assert all(c.page_content.startswith("[CDC art. 54-A]") for c in chunks)
    assert all(len(c.page_content) <= 1000 + len("[CDC art. 54-A] ") for c in chunks)


def test_metadados_do_trecho(docs_dir):
    chunk = next(c for c in load_chunks(docs_dir) if c.metadata["article"] == "54-B")
    assert chunk.metadata == {"source_id": "cdc", "label": "CDC", "article": "54-B", "url": "https://planalto/cdc"}
    assert re.fullmatch(r"cdc:54-B:0:[0-9a-f]{12}", chunk.id)


def test_nota_vira_trecho_rotulado(docs_dir):
    note = next(c for c in load_chunks(docs_dir) if c.metadata["source_id"] == "nota:teto")
    assert note.page_content.startswith("[Nota: Teto do rotativo]")
    assert note.metadata["url"] == "https://exemplo"


def test_indexar_duas_vezes_nao_duplica(docs_dir, tmp_path, store):
    before = len(store.get()["ids"])
    again = build_vector_store(docs_dir, tmp_path / "chroma", DeterministicFakeEmbedding(size=32))
    assert len(again.get()["ids"]) == before == len(load_chunks(docs_dir))


def test_search_norms_devolve_texto_rotulado(store):
    tool = make_search_tool(store, k=2)
    assert tool.name == "search_norms"
    result = tool.invoke({"query": "pergunta sem relação nenhuma"})
    assert result.count("[") == 2


def test_grade_chunks_sim_e_nao():
    assert grade_chunks("q", "ctx", RunnableLambda(lambda _: GradeDocuments(binary_score="sim"))) is True
    assert grade_chunks("q", "ctx", RunnableLambda(lambda _: GradeDocuments(binary_score="nao"))) is False


def test_rewrite_query_devolve_texto_do_modelo():
    model = GenericFakeChatModel(messages=iter([AIMessage(content="limite de juros do rotativo do cartão")]))
    assert rewrite_query("o juro do cartão tem teto?", model) == "limite de juros do rotativo do cartão"


class FlakyEmbeddings(DeterministicFakeEmbedding):
    """Falha com erro de cota na primeira chamada, como o plano gratuito do Gemini."""

    calls: int = 0

    def embed_documents(self, texts):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
        return super().embed_documents(texts)


def test_indexacao_espera_e_tenta_de_novo_quando_estoura_a_cota(docs_dir, tmp_path):
    waits = []
    store = build_vector_store(docs_dir, tmp_path / "chroma", FlakyEmbeddings(size=32), sleep=waits.append)
    assert waits == [60]
    assert len(store.get()["ids"]) == len(load_chunks(docs_dir))


def test_indexacao_completa_indice_pela_metade(docs_dir, tmp_path):
    from langchain_chroma import Chroma

    chunks = load_chunks(docs_dir)
    partial = Chroma(collection_name="normas", embedding_function=DeterministicFakeEmbedding(size=32),
                     persist_directory=str(tmp_path / "chroma"), collection_metadata={"hnsw:space": "cosine"})
    partial.add_documents(chunks[:2], ids=[c.id for c in chunks[:2]])
    store = build_vector_store(docs_dir, tmp_path / "chroma", DeterministicFakeEmbedding(size=32))
    assert sorted(store.get()["ids"]) == sorted(c.id for c in chunks)


def test_indexacao_em_lotes(docs_dir, tmp_path):
    seen = []

    class Counting(DeterministicFakeEmbedding):
        def embed_documents(self, texts):
            seen.append(len(texts))
            return super().embed_documents(texts)

    build_vector_store(docs_dir, tmp_path / "chroma", Counting(size=32), batch_size=2)
    assert max(seen) <= 2


def test_nota_alterada_e_reindexada_sem_o_texto_antigo(docs_dir, tmp_path, store):
    note = docs_dir / "notas" / "teto.md"
    note.write_text(note.read_text().replace("100%", "150%"))
    store = build_vector_store(docs_dir, tmp_path / "chroma", DeterministicFakeEmbedding(size=32))
    texts = store.get()["documents"]
    assert any("150%" in t for t in texts)
    assert not any("100% do valor original" in t for t in texts)


def test_artigo_removido_sai_do_indice(docs_dir, tmp_path, store):
    cdc = docs_dir / "cdc.txt"
    cdc.write_text(cdc.read_text().split("\n\nArt. 54-B")[0] + "\n")
    store = build_vector_store(docs_dir, tmp_path / "chroma", DeterministicFakeEmbedding(size=32))
    assert not any(":54-B:" in i for i in store.get()["ids"])
