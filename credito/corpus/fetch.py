"""Download dos textos oficiais no Planalto e na API de normativos do BCB."""

from __future__ import annotations

import io
import json
import re
import time
from typing import Callable
from urllib.parse import quote

import httpx

from credito.corpus.sources import Source

BCB_API = "https://www.bcb.gov.br/api/conteudo/app/normativos/exibenormativo"
BCB_FILES = "https://normativos.bcb.gov.br/Lists/Normativos/Attachments"
# o Planalto deixa a conexão pendurada para user-agents que não são de navegador
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

Get = Callable[[str], bytes]


class FetchError(Exception):
    """A fonte não pôde ser baixada ou não está vigente."""


def http_get(url: str) -> bytes:
    """Baixa a URL com até 3 tentativas e espera crescente."""
    for attempt in range(3):
        try:
            response = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise AssertionError("inalcançável")


def latest_consolidated_pdf(documentos: str | None) -> str | None:
    """Escolhe o PDF consolidado (_vN_L) de maior versão na lista de documentos do BCB."""
    files = re.findall(r"([\w]+_v(\d+)_L\.pdf)", documentos or "")
    if not files:
        return None
    return max(files, key=lambda item: int(item[1]))[0]


def pdf_to_text(data: bytes) -> str:
    """Extrai o texto de um PDF."""
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def fetch_source(source: Source, get: Get = http_get) -> tuple[str, dict]:
    """Baixa a fonte e devolve o conteúdo bruto (HTML ou texto) e os metadados."""
    if source.kind == "planalto":
        return get(source.url).decode("cp1252"), {"url": source.url, "revogado": False,
                                                   "atualizacoes": None, "arquivo": None}
    return _fetch_bcb(source, get)


def _fetch_bcb(source: Source, get: Get) -> tuple[str, dict]:
    url = f"{BCB_API}?p1={quote(source.bcb_type)}&p2={source.bcb_number}"
    items = json.loads(get(url)).get("conteudo") or []
    if not items:
        raise FetchError(
            f"{source.id}: a API do BCB não achou '{source.bcb_type} {source.bcb_number}'; confira o tipo "
            "(resoluções do CMN anteriores a 2020 usam 'Resolução', as novas 'Resolução CMN')"
        )
    item = items[0]
    year = str(item.get("Data") or "")[:4]
    if source.bcb_year and year != source.bcb_year:
        raise FetchError(
            f"{source.id}: a API devolveu '{item.get('Titulo')}' de {year}, não a de {source.bcb_year}; "
            "o tipo da norma provavelmente está errado"
        )
    if str(item.get("Revogado")).lower() == "true":
        raise FetchError(f"{source.id}: a norma consta como revogada no BCB")
    meta = {"url": url, "revogado": False, "atualizacoes": item.get("Atualizacoes"), "arquivo": None}
    pdf = latest_consolidated_pdf(item.get("Documentos"))
    if pdf is None:
        return item.get("Texto") or "", meta
    meta["arquivo"] = pdf
    return pdf_to_text(get(f"{BCB_FILES}/{item['Id']}/{pdf}")), meta
