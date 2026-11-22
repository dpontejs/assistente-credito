"""RAG das normas: índice no Chroma, busca rotulada e as etapas de avaliar e reescrever (padrão do nb12)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Literal

import yaml
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool, tool
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field

from credito.corpus.parse import split_articles

COLLECTION = "normas"
SPLITTER = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)

GRADE_PROMPT = """# Papel
Você avalia se os trechos de leis e normas recuperados ajudam a responder a pergunta de um consumidor.

# Regras
- Responda "sim" se algum trecho trata do assunto da pergunta, mesmo sem responder tudo.
- Responda "nao" se os trechos falam de outro assunto.

<pergunta>
{question}
</pergunta>

<contexto>
{context}
</contexto>"""

REWRITE_PROMPT = """# Papel
Você reescreve perguntas de consumidores para buscar em leis e normas brasileiras de crédito.

# Regras
- Use os termos técnicos das normas (crédito rotativo, portabilidade, margem consignável, mínimo existencial, encargos).
- Devolva só a nova consulta, em uma linha, sem explicação.

<pergunta>
{question}
</pergunta>"""


class GradeDocuments(BaseModel):
    """Veredito sobre a relevância dos trechos recuperados."""

    binary_score: Literal["sim", "nao"] = Field(description="'sim' se os trechos tratam da pergunta, senão 'nao'")


def _split(text: str, label: str, metadata: dict, id_prefix: str) -> list[Document]:
    """Quebra um artigo ou nota em pedaços, cada um começando com o rótulo da fonte."""
    return [
        Document(page_content=f"[{label}] {piece}", metadata=metadata, id=f"{id_prefix}:{k}")
        for k, piece in enumerate(SPLITTER.split_text(text))
    ]


def load_chunks(docs_dir: Path) -> list[Document]:
    """Lê os textos baixados e as notas curadas e devolve os trechos rotulados, com ids estáveis."""
    docs_dir = Path(docs_dir)
    chunks: list[Document] = []
    for meta_file in sorted(docs_dir.glob("*.json")):
        meta = json.loads(meta_file.read_text())
        text = (docs_dir / f"{meta['id']}.txt").read_text()
        for article, body in split_articles(text):
            metadata = {"source_id": meta["id"], "label": meta["label"], "article": article, "url": meta["url"]}
            chunks += _split(body, f"{meta['label']} art. {article}", metadata, f"{meta['id']}:{article}")
    for note in sorted((docs_dir / "notas").glob("*.md")):
        _, head, body = note.read_text().split("---", 2)
        front = yaml.safe_load(head)
        metadata = {"source_id": f"nota:{note.stem}", "label": "Nota", "article": "", "url": front["sources"][0]}
        chunks += _split(body.strip(), f"Nota: {front['title']}", metadata, f"nota:{note.stem}")
    return chunks


def _is_rate_limit(error: Exception) -> bool:
    text = str(error)
    return "429" in text or "RESOURCE_EXHAUSTED" in text


def build_vector_store(
    docs_dir: Path,
    persist_dir: Path,
    embeddings: Embeddings,
    batch_size: int = 80,
    sleep: Callable[[float], None] = time.sleep,
) -> Chroma:
    """Abre o índice persistido e indexa, em lotes, só os trechos que ainda faltam.

    Lotes de 80 cabem na cota gratuita do Gemini (100 por minuto); se a cota estourar,
    espera um minuto e tenta o mesmo lote de novo. Um índice interrompido é completado
    na próxima execução, sem duplicar o que já está lá.
    """
    store = Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings,
        persist_directory=str(persist_dir),
        collection_metadata={"hnsw:space": "cosine"},
    )
    indexed = set(store.get()["ids"])
    missing = [chunk for chunk in load_chunks(docs_dir) if chunk.id not in indexed]
    for start in range(0, len(missing), batch_size):
        batch = missing[start:start + batch_size]
        for attempt in range(5):
            try:
                store.add_documents(batch, ids=[chunk.id for chunk in batch])
                break
            except Exception as error:  # o provedor de embeddings embrulha o 429 em exceções próprias
                if not _is_rate_limit(error) or attempt == 4:
                    raise
                sleep(60)
    return store


def format_docs(docs: list[Document]) -> str:
    """Junta os trechos separados por linha em branco; o rótulo da fonte já está no texto."""
    return "\n\n".join(doc.page_content for doc in docs)


def make_search_tool(store: Chroma, k: int = 4) -> BaseTool:
    """Cria a ferramenta de busca nas normas usada pelo agente."""
    retriever = store.as_retriever(search_kwargs={"k": k})

    @tool
    def search_norms(query: str) -> str:
        """Busca trechos das leis e normas brasileiras sobre crédito ao consumidor (CDC, superendividamento, cartão, cheque especial, consignado, portabilidade, tarifas). Cada trecho vem com a fonte entre colchetes."""
        return format_docs(retriever.invoke(query))

    return search_norms


def grade_chunks(question: str, context: str, grader: Runnable) -> bool:
    """Diz se os trechos ajudam a responder; grader = model.with_structured_output(GradeDocuments)."""
    verdict = grader.invoke(GRADE_PROMPT.format(question=question, context=context))
    return verdict.binary_score == "sim"


def rewrite_query(question: str, model: Runnable) -> str:
    """Reformula a pergunta com os termos das normas para buscar de novo."""
    return model.invoke(REWRITE_PROMPT.format(question=question)).content.strip()


def default_embeddings() -> Embeddings:
    """Embeddings do Gemini com 768 dimensões, como no lab 01."""
    from langchain.embeddings import init_embeddings

    return init_embeddings("google_genai:gemini-embedding-001", output_dimensionality=768)
