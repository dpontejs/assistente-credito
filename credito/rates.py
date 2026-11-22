"""Taxas de juros de mercado da API de dados abertos do Banco Central, com cache local."""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode

import httpx

URL = "https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/TaxasJurosDiariaPorInicioPeriodo"

# chave interna -> nome exato da modalidade no BCB (pessoa física)
MODALITIES = {
    "cartao_rotativo": "Cartão de crédito - rotativo total - Prefixado",
    "cartao_parcelado": "Cartão de crédito - parcelado - Prefixado",
    "cheque_especial": "Cheque especial - Prefixado",
    "pessoal": "Crédito pessoal não consignado - Prefixado",
    "consignado_inss": "Crédito pessoal consignado INSS - Prefixado",
    "consignado_privado": "Crédito pessoal consignado privado - Prefixado",
    "consignado_publico": "Crédito pessoal consignado público - Prefixado",
    "veiculo": "Aquisição de veículos - Prefixado",
}

Fetch = Callable[[str, dict], dict]


class RatesUnavailable(Exception):
    """A API do BCB não respondeu e não há cache para a modalidade."""


@dataclass(frozen=True)
class MarketRate:
    kind: str
    period_start: str
    median: float
    n_institutions: int
    from_cache: bool


def build_url(params: dict, url: str = URL) -> str:
    """Monta a URL com espaços como %20, porque o OData do BCB não aceita '+'."""
    return f"{url}?{urlencode({**params, '$format': 'json'}, quote_via=quote)}"


def http_get(url: str, params: dict) -> dict:
    """Faz o GET na API do BCB e devolve o JSON."""
    response = httpx.get(build_url(params, url), timeout=30)
    response.raise_for_status()
    return response.json()


class RatesClient:
    """Consulta a mediana das taxas dos bancos por modalidade, caindo no cache sem rede."""

    def __init__(self, cache_path: Path, fetch: Fetch = http_get):
        self.cache_path = Path(cache_path)
        self.fetch = fetch

    def market_rate(self, kind: str) -> MarketRate:
        """Devolve a mediana mais recente da modalidade."""
        modality = MODALITIES[kind]
        try:
            rate = self._from_api(kind, modality)
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as error:
            cached = self._read_cache().get(kind)
            if cached is None:
                raise RatesUnavailable(f"API do BCB indisponível e sem cache para {kind}") from error
            return MarketRate(**{**cached, "from_cache": True})
        self._write_cache(kind, rate)
        return rate

    def _from_api(self, kind: str, modality: str) -> MarketRate:
        """Busca o período mais recente e as taxas de todos os bancos nele."""
        base = f"Segmento eq 'PESSOA FÍSICA' and Modalidade eq '{modality}'"
        latest = self.fetch(URL, {"$filter": base, "$orderby": "InicioPeriodo desc", "$top": 1})
        period = latest["value"][0]["InicioPeriodo"]
        rows = self.fetch(URL, {"$filter": f"{base} and InicioPeriodo eq '{period}'", "$top": 1000})
        rates = [row["TaxaJurosAoMes"] for row in rows["value"]]
        if not rates:
            raise ValueError(f"nenhuma taxa para {kind} em {period}")
        return MarketRate(kind, period, statistics.median(rates), len(rates), from_cache=False)

    def _read_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}
        return json.loads(self.cache_path.read_text())

    def _write_cache(self, kind: str, rate: MarketRate) -> None:
        cache = self._read_cache()
        cache[kind] = {k: v for k, v in asdict(rate).items() if k != "from_cache"}
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
