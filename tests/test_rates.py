import httpx
import pytest

from credito.rates import MODALITIES, RatesClient, RatesUnavailable


def fake_fetch(rates: list[float], period: str = "2026-10-29"):
    """Devolve um fetch falso que responde como a API do BCB."""

    def fetch(url: str, params: dict) -> dict:
        if params.get("$top") == 1:
            return {"value": [{"InicioPeriodo": period}]}
        return {"value": [{"InicioPeriodo": period, "TaxaJurosAoMes": r} for r in rates]}

    return fetch


def offline_fetch(url: str, params: dict) -> dict:
    raise httpx.ConnectError("sem rede")


def test_market_rate_mediana(tmp_path):
    client = RatesClient(tmp_path / "cache.json", fetch=fake_fetch([20, 10, 15.79]))
    rate = client.market_rate("cartao_rotativo")
    assert rate.median == 15.79
    assert rate.n_institutions == 3
    assert rate.period_start == "2026-10-29"
    assert rate.from_cache is False


def test_market_rate_usa_cache_sem_rede(tmp_path):
    cache = tmp_path / "cache.json"
    RatesClient(cache, fetch=fake_fetch([20, 10, 15.79])).market_rate("cartao_rotativo")
    rate = RatesClient(cache, fetch=offline_fetch).market_rate("cartao_rotativo")
    assert rate.median == 15.79
    assert rate.from_cache is True


def test_market_rate_sem_rede_e_sem_cache(tmp_path):
    with pytest.raises(RatesUnavailable):
        RatesClient(tmp_path / "cache.json", fetch=offline_fetch).market_rate("cartao_rotativo")


def test_market_rate_modalidade_desconhecida(tmp_path):
    with pytest.raises(KeyError):
        RatesClient(tmp_path / "cache.json", fetch=fake_fetch([1])).market_rate("hipoteca")


def test_modalidades_cobrem_o_spec():
    assert set(MODALITIES) == {
        "cartao_rotativo", "cartao_parcelado", "cheque_especial", "pessoal",
        "consignado_inss", "consignado_privado", "consignado_publico", "veiculo",
    }


@pytest.mark.network
def test_bcb_real(tmp_path):
    rate = RatesClient(tmp_path / "cache.json").market_rate("cartao_rotativo")
    assert rate.median > 1
    assert rate.n_institutions > 10


def test_build_url_codifica_espaco_como_porcento_20():
    from credito.rates import build_url

    url = build_url({"$filter": "Segmento eq 'PESSOA FÍSICA'", "$top": 1})
    assert "+" not in url
    assert "Segmento%20eq%20%27PESSOA%20F%C3%8DSICA%27" in url
    assert url.endswith("%24top=1&%24format=json")
