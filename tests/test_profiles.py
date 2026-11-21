import pytest
from pydantic import ValidationError

from credito.profiles import Debt, ProfileStore


@pytest.fixture
def store(tmp_path):
    store = ProfileStore(tmp_path / "profiles.db")
    store.seed()
    return store


def rotativo(balance: float) -> Debt:
    return Debt(kind="cartao_rotativo", creditor="Banco Alfa", balance=balance, monthly_rate=14.0)


def test_seed_cria_usuarios_e_dividas(store):
    ana = store.get_profile("ana")
    assert ana["name"] == "Ana Souza"
    assert ana["income"] == 4500
    assert {d["kind"] for d in ana["debts"]} == {"cartao_rotativo", "consignado_privado"}
    assert ana["plan"] is None


def test_seed_idempotente(store):
    store.seed()
    total = sum(len(store.get_profile(u)["debts"]) for u in ("ana", "bruno", "carla"))
    assert total == 6


def test_save_debt_idempotente(store):
    first = store.save_debt("ana", rotativo(4000))
    second = store.save_debt("ana", rotativo(3500))
    debts = [d for d in store.get_profile("ana")["debts"] if d["kind"] == "cartao_rotativo"]
    assert first == second
    assert len(debts) == 1
    assert debts[0]["balance"] == 3500


def test_remove_debt_de_outro_usuario(store):
    ana_debt = store.get_profile("ana")["debts"][0]["id"]
    assert store.remove_debt("bruno", ana_debt) is False
    assert ana_debt in [d["id"] for d in store.get_profile("ana")["debts"]]


def test_remove_debt_do_proprio_usuario(store):
    ana_debt = store.get_profile("ana")["debts"][0]["id"]
    assert store.remove_debt("ana", ana_debt) is True
    assert ana_debt not in [d["id"] for d in store.get_profile("ana")["debts"]]


def test_plano_mais_recente(store):
    store.save_plan("ana", "plano 1")
    store.save_plan("ana", "plano 2")
    assert store.get_profile("ana")["plan"] == "plano 2"


def test_usuario_inexistente(store):
    assert store.get_profile("zeca") is None


def test_debt_modalidade_invalida():
    with pytest.raises(ValidationError):
        Debt(kind="hipoteca", creditor="X", balance=1, monthly_rate=1)


def test_debt_saldo_nao_positivo():
    with pytest.raises(ValidationError):
        Debt(kind="pessoal", creditor="X", balance=0, monthly_rate=1)


def test_save_debt_usuario_inexistente(store):
    with pytest.raises(ValueError, match="usuário"):
        store.save_debt("zeca", rotativo(100))


def test_save_debt_credor_ignora_maiusculas_e_espacos(store):
    store.save_debt("ana", Debt(kind="cartao_rotativo", creditor="  banco alfa ", balance=3000, monthly_rate=14))
    debts = [d for d in store.get_profile("ana")["debts"] if d["kind"] == "cartao_rotativo"]
    assert len(debts) == 1
    assert debts[0]["balance"] == 3000
