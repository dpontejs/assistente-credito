"""Perfil persistente do usuário em SQLite: renda, dívidas e plano de quitação."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from credito.rates import MODALITIES

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    income REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    creditor TEXT NOT NULL,
    balance REAL NOT NULL,
    monthly_rate REAL NOT NULL,
    installments_left INTEGER,
    UNIQUE(user_id, kind, creditor)
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Debt(BaseModel):
    kind: Literal[tuple(MODALITIES)] = Field(description="Modalidade da dívida")
    creditor: str = Field(description="Nome do credor, como o usuário informou")
    balance: float = Field(gt=0, description="Saldo devedor em reais")
    monthly_rate: float = Field(ge=0, description="Taxa de juros em % ao mês")
    installments_left: int | None = Field(default=None, gt=0, description="Parcelas restantes, se parcelada")


# usuários fictícios da demo; credores inventados, nenhum banco real
SEED = {
    ("ana", "Ana Souza", 4500): [
        Debt(kind="cartao_rotativo", creditor="Banco Alfa", balance=4000, monthly_rate=14.0),
        Debt(kind="consignado_privado", creditor="Banco Beta", balance=15000, monthly_rate=2.1, installments_left=36),
    ],
    ("bruno", "Bruno Lima", 3200): [
        Debt(kind="cheque_especial", creditor="Banco Gama", balance=2500, monthly_rate=7.9),
        Debt(kind="pessoal", creditor="Financeira Delta", balance=8000, monthly_rate=6.5, installments_left=24),
    ],
    ("carla", "Carla Mendes", 7800): [
        Debt(kind="veiculo", creditor="Banco Alfa", balance=32000, monthly_rate=2.4, installments_left=40),
        Debt(kind="cartao_parcelado", creditor="Banco Beta", balance=3000, monthly_rate=9.0, installments_left=10),
    ],
}


class ProfileStore:
    """Lê e grava perfis; toda operação é filtrada pelo user_id recebido."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def seed(self) -> None:
        """Cria os usuários fictícios que ainda não existem, sem mexer nos que já existem."""
        for (user_id, name, income), debts in SEED.items():
            with closing(self._connect()) as conn, conn:
                created = conn.execute(
                    "INSERT OR IGNORE INTO users (id, name, income) VALUES (?, ?, ?)", (user_id, name, income)
                ).rowcount
            if created:
                for debt in debts:
                    self.save_debt(user_id, debt)

    def get_profile(self, user_id: str) -> dict | None:
        """Devolve renda, dívidas e o plano mais recente do usuário."""
        with closing(self._connect()) as conn:
            user = conn.execute("SELECT id, name, income FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None:
                return None
            debts = conn.execute(
                "SELECT id, kind, creditor, balance, monthly_rate, installments_left FROM debts"
                " WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
            plan = conn.execute(
                "SELECT text FROM plans WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
            ).fetchone()
        return {**dict(user), "debts": [dict(d) for d in debts], "plan": plan["text"] if plan else None}

    def save_debt(self, user_id: str, debt: Debt) -> int:
        """Insere a dívida ou atualiza a existente do mesmo tipo e credor; devolve o id."""
        with closing(self._connect()) as conn, conn:
            if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                raise ValueError(f"usuário {user_id} não existe")
            row = conn.execute(
                "INSERT INTO debts (user_id, kind, creditor, balance, monthly_rate, installments_left)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(user_id, kind, creditor) DO UPDATE SET"
                " balance = excluded.balance, monthly_rate = excluded.monthly_rate,"
                " installments_left = excluded.installments_left"
                " RETURNING id",
                (user_id, debt.kind, debt.creditor, debt.balance, debt.monthly_rate, debt.installments_left),
            ).fetchone()
        return row["id"]

    def remove_debt(self, user_id: str, debt_id: int) -> bool:
        """Remove a dívida só se ela pertencer ao usuário."""
        with closing(self._connect()) as conn, conn:
            return conn.execute("DELETE FROM debts WHERE id = ? AND user_id = ?", (debt_id, user_id)).rowcount > 0

    def save_plan(self, user_id: str, text: str) -> None:
        """Guarda um novo plano; o mais recente é o que vale."""
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT INTO plans (user_id, text) VALUES (?, ?)", (user_id, text))
