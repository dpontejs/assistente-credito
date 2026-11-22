"""Fontes do núcleo do corpus normativo (ver data/docs/FONTES.md)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PLANALTO = "https://www.planalto.gov.br/ccivil_03"


@dataclass(frozen=True)
class Source:
    id: str
    label: str  # prefixo do rótulo dos trechos, como em [CDC art. 54-A]
    title: str
    kind: Literal["planalto", "bcb"]
    url: str | None = None
    bcb_type: str | None = None
    bcb_number: str | None = None
    bcb_year: str | None = None  # confere que a API devolveu a norma certa, não outra de mesmo número
    articles: tuple[str, ...] | None = None  # None indexa todos os artigos


CDC_ARTICLES = (
    "6º", "39", "42", "42-A", "43", "51", "52",
    "54-A", "54-B", "54-C", "54-D", "54-E", "54-F", "54-G",
    "104-A", "104-B", "104-C",
)


def bcb(id: str, label: str, title: str, bcb_type: str, number: str, year: str) -> Source:
    """Atalho para uma norma do CMN ou do BCB."""
    return Source(id=id, label=label, title=title, kind="bcb", bcb_type=bcb_type, bcb_number=number, bcb_year=year)


SOURCES: list[Source] = [
    Source("cdc", "CDC", "Código de Defesa do Consumidor (compilado, com a Lei 14.181/2021)", "planalto",
           url=f"{PLANALTO}/leis/l8078compilado.htm", articles=CDC_ARTICLES),
    Source("dec11150", "Decreto 11.150", "Mínimo existencial (com o Decreto 11.567/2023)", "planalto",
           url=f"{PLANALTO}/_ato2019-2022/2022/decreto/d11150.htm"),
    Source("lei14690", "Lei 14.690", "Desenrola: teto do rotativo e portabilidade da fatura", "planalto",
           url=f"{PLANALTO}/_ato2023-2026/2023/lei/l14690.htm", articles=("27", "28")),
    Source("lei10820", "Lei 10.820", "Crédito consignado (compilado)", "planalto",
           url=f"{PLANALTO}/leis/2003/L10.820compilado.htm"),
    bcb("res4549", "Res. 4.549", "Financiamento do saldo da fatura do cartão (rotativo)", "Resolução", "4549", "2017"),
    bcb("bcb96", "Res. BCB 96", "Contas de pagamento e fatura do cartão", "Resolução BCB", "96", "2021"),
    bcb("cmn4882", "Res. CMN 4.882", "Encargos por atraso", "Resolução CMN", "4882", "2020"),
    bcb("res4765", "Res. 4.765", "Cheque especial", "Resolução", "4765", "2019"),
    bcb("cmn5057", "Res. CMN 5.057", "Portabilidade de crédito", "Resolução CMN", "5057", "2022"),
    bcb("res3919", "Res. 3.919", "Tarifas bancárias", "Resolução", "3919", "2010"),
    bcb("cmn4881", "Res. CMN 4.881", "Custo efetivo total (CET)", "Resolução CMN", "4881", "2020"),
]
