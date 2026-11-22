"""Baixa o núcleo do corpus normativo para data/docs/.

    uv run python scripts/download_corpus.py

Grava <id>.txt (texto limpo, um artigo por bloco) e <id>.json (metadados).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

from credito.corpus.fetch import FetchError, fetch_source, http_get
from credito.corpus.parse import html_to_text, split_articles
from credito.corpus.sources import SOURCES, Source

OUT = Path(__file__).resolve().parent.parent / "data" / "docs"


def clean(raw: str, meta: dict) -> str:
    """HTML vira texto; texto de PDF só tem os espaços normalizados."""
    if meta["arquivo"] is None:
        return html_to_text(raw)
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines())


def download_source(source: Source, out_dir: Path, get=http_get) -> int:
    """Baixa uma fonte, filtra os artigos e grava os arquivos; devolve quantos artigos ficaram."""
    raw, meta = fetch_source(source, get=get)
    articles = split_articles(clean(raw, meta))
    if source.articles is not None:
        articles = [(label, text) for label, text in articles if label in source.articles]
    if not articles:
        raise FetchError(f"{source.id}: nenhum artigo encontrado no texto baixado")
    (out_dir / f"{source.id}.txt").write_text("\n\n".join(text for _, text in articles) + "\n")
    meta = {**meta, "id": source.id, "label": source.label, "title": source.title,
            "articles": [label for label, _ in articles], "downloaded": date.today().isoformat()}
    (out_dir / f"{source.id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return len(articles)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    failures = 0
    for source in SOURCES:
        try:
            print(f"{source.id}: {download_source(source, OUT)} artigos")
        except (FetchError, OSError, ValueError) as error:
            failures += 1
            print(f"{source.id}: ERRO {error}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
