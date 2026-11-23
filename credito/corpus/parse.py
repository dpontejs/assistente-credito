"""Limpeza do HTML/PDF oficial e divisão do texto em artigos."""

from __future__ import annotations

import re
from html.parser import HTMLParser

BLOCKS = {"p", "div", "tr", "li", "table", "br", "h1", "h2", "h3", "h4", "h5", "h6"}
STRUCK_TAGS = {"strike", "s", "del"}
ARTICLE = re.compile(r"^Art\.\s*(\d+)\s*(?:[º°]|o(?=[\s.\-]))?\s*(?:-\s*([A-Z])\b)?", re.M)
# rodapé das páginas do Planalto e assinaturas depois do último artigo
TAIL = re.compile(r"^(Brasília, \d|Este texto não substitui)", re.M)


class _TextExtractor(HTMLParser):
    """Junta o texto visível, pulando elementos riscados (<strike>, <s>, <del> ou CSS line-through)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_tag: str | None = None
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.skip_tag:
            self.skip_depth += tag == self.skip_tag
            return
        style = (dict(attrs).get("style") or "").replace(" ", "").lower()
        if tag in STRUCK_TAGS or "line-through" in style:
            self.skip_tag, self.skip_depth = tag, 1
        elif tag in BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.skip_tag:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip_tag = None
            return
        if tag in BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_tag:
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(raw: str) -> str:
    """Tira o texto riscado (revogado), as tags e as entidades, deixando um parágrafo por bloco."""
    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n"))
    return "\n\n".join(line for line in lines if line)


def article_label(number: str, suffix: str | None) -> str:
    """Normaliza o número do artigo: 1 a 9 levam º (técnica legislativa) e o sufixo é mantido."""
    label = f"{number}º" if int(number) <= 9 else number
    return f"{label}-{suffix}" if suffix else label


def split_articles(text: str) -> list[tuple[str, str]]:
    """Divide o texto em (artigo, texto do artigo), descartando o que vem antes do primeiro artigo."""
    tail = TAIL.search(text)
    if tail:
        text = text[: tail.start()]
    matches = list(ARTICLE.finditer(text))
    articles = []
    for match, following in zip(matches, matches[1:] + [None]):
        end = following.start() if following else len(text)
        body = text[match.start():end].strip()
        articles.append((article_label(match.group(1), match.group(2)), body))
    return articles
