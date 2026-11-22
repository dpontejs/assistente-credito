"""Roda os 10 casos de ponta a ponta, julga as respostas e compara modelos.

    uv run python -m evals.run --model gemini-3.5-flash-lite --model gemini-3.6-flash

Cada caso roda num banco de perfis e num checkpointer temporários, a partir do
seed. Grava evals/results/<modelo>.json e reescreve evals/RESULTADOS.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from credito.graph import as_text
from credito.profiles import ProfileStore
from credito.ui import turns
from evals.cases import CASES, Case, EvalRun

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evals" / "results"
JUDGE_MODEL = "google_genai:gemini-3.8-flash"
TURN_TIMEOUT = 300  # por turno

# USD por 1M tokens, página oficial de preços em 22/11/2026; a saída inclui tokens de raciocínio
PRICES = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.6-flash": (0.75, 3.75),
}

JUDGE_PROMPT = """# Papel
Você avalia a resposta de um assistente de dívidas e crédito contra o resultado esperado.

# Regras
- "correct" é verdadeiro se a resposta final entrega o essencial do esperado (números, regra, recusa), mesmo com outras palavras ou detalhes a mais.
- Números podem diferir só por arredondamento. Uma afirmação errada sobre regra ou valor torna a resposta incorreta.
- Em casos com mais de um turno, julgue a conversa inteira.

<conversa>
{conversation}
</conversa>

<esperado>
{expected}
</esperado>"""


class Verdict(BaseModel):
    """Veredito do juiz."""

    correct: bool = Field(description="A resposta entrega o resultado esperado")
    reason: str = Field(description="Justificativa curta em português")


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Custo em dólares pelos preços da tabela."""
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def score(run: EvalRun, verdict: Verdict | None) -> dict:
    """Aprovado só se não houve erro, as ferramentas e skills esperadas apareceram, as checagens passaram e o juiz aprovou."""
    used_tools = {tool for turn in run.tools_per_turn for tool in turn}
    used_skills = {skill for turn in run.skills_per_turn for skill in turn}
    tools_ok = run.case.tools <= used_tools and run.case.skills <= used_skills
    checks_failed = [] if run.error else [reason for check in run.case.checks if (reason := check(run))]
    judged = verdict is not None
    passed = run.error is None and tools_ok and not checks_failed and judged and verdict.correct
    return {"passed": passed, "tools_ok": tools_ok, "checks_failed": checks_failed, "judged": judged,
            "verdict": verdict.reason if verdict else None}


async def execute(case: Case, model: str) -> EvalRun:
    """Roda os turnos do caso num ambiente temporário e coleta respostas, ferramentas, tempo e tokens."""
    from credito.assistant import open_assistant

    run = EvalRun(case=case, answers=[], tools_per_turn=[], skills_per_turn=[])
    usage = UsageMetadataCallbackHandler()
    with tempfile.TemporaryDirectory() as tmp:
        profiles = Path(tmp) / "profiles.db"
        ProfileStore(profiles).seed()
        threads = {name: f"eval-{case.id}-{name}-{uuid.uuid4().hex[:6]}" for name, _ in case.turns}
        try:
            async with open_assistant(db_path=Path(tmp) / "checkpoints.db", model_name=f"google_genai:{model}",
                                      profiles_db=profiles) as assistant:
                for thread, text in case.turns:
                    config = {"configurable": {"thread_id": threads[thread]}, "callbacks": [usage]}
                    start = time.perf_counter()  # latência só dos turnos, sem abrir servidores e índice
                    state = await asyncio.wait_for(
                        assistant.graph.ainvoke({"messages": [HumanMessage(text)], "user_id": case.user}, config),
                        TURN_TIMEOUT,
                    )
                    run.seconds += time.perf_counter() - start
                    turn = turns(state["messages"])[-1]
                    run.answers.append(turn.answer)
                    run.tools_per_turn.append(turn.tools)
                    run.skills_per_turn.append(turn.skills)
                histories = []
                for thread_id in threads.values():
                    snapshot = await assistant.graph.aget_state({"configurable": {"thread_id": thread_id}})
                    histories += [as_text(m.content) for m in snapshot.values.get("messages", [])]
                run.history = "\n".join(histories)
        except Exception as error:  # o caso reprova com o erro registrado; a rodada segue
            run.error = f"{type(error).__name__}: {error}"[:500]
    for counts in usage.usage_metadata.values():
        run.input_tokens += counts.get("input_tokens", 0)
        run.output_tokens += counts.get("output_tokens", 0)
    return run


def judge(run: EvalRun, judge_model) -> tuple[Verdict | None, str | None]:
    """Pede o veredito ao juiz; falha do juiz vira (None, erro): caso não julgado, nunca aprovado."""
    conversation = "\n\n".join(
        f"Usuário: {text}\nAssistente: {answer}" for (_, text), answer in zip(run.case.turns, run.answers)
    )
    try:
        verdict = judge_model.invoke(JUDGE_PROMPT.format(conversation=conversation, expected=run.case.expected))
    except Exception as error:
        return None, f"{type(error).__name__}: {error}"[:300]
    return verdict, None if verdict is not None else "saída estruturada vazia"


def merge_rows(old: list[dict], new: list[dict]) -> list[dict]:
    """Substitui no resultado anterior só os casos que rodaram agora, mantendo a ordem por id."""
    by_id = {row["id"]: row for row in old} | {row["id"]: row for row in new}
    return [by_id[key] for key in sorted(by_id)]


def run_model(model: str, judge_model, case_ids: set[int] | None = None) -> list[dict]:
    """Roda os casos (todos ou os pedidos) com um modelo e grava o JSON de resultados."""
    rows = []
    for case in CASES:
        if case_ids and case.id not in case_ids:
            continue
        run = asyncio.run(execute(case, model))
        verdict, judge_error = judge(run, judge_model) if run.error is None else (None, None)
        result = {**score(run, verdict), "judge_error": judge_error}
        rows.append({
            "id": case.id, "title": case.title, "component": case.component, "challenging": case.challenging,
            "input": [text for _, text in case.turns], "expected": case.expected, "answers": run.answers,
            "tools": run.tools_per_turn, "skills": run.skills_per_turn, "seconds": round(run.seconds, 1),
            "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
            "cost_usd": round(cost_usd(model, run.input_tokens, run.output_tokens), 5),
            "error": run.error, **result,
        })
        print(f"{model} caso {case.id}: {'aprovado' if result['passed'] else 'reprovado'} ({run.seconds:.0f} s)")
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{model}.json"
    if case_ids and path.exists():
        rows = merge_rows(json.loads(path.read_text()), rows)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    return rows


def observation(row: dict) -> str:
    """Motivo mostrado na tabela: erro, checagens que falharam, falta de julgamento ou o veredito."""
    if row["error"]:
        return row["error"]
    if row["checks_failed"]:
        return "; ".join(row["checks_failed"])
    if not row["judged"]:
        return f"não julgado: {row.get('judge_error') or 'sem veredito'}"
    return row["verdict"] or ""


def write_report() -> None:
    """Reescreve evals/RESULTADOS.md a partir de todos os JSON em evals/results/."""
    lines = ["# Resultados da avaliação", "", "Gerado por `uv run python -m evals.run`. Juiz: "
             f"`{JUDGE_MODEL}`. Custos pelos preços oficiais de 22/11/2026, sem os embeddings da busca e sem o juiz. "
             "Latência = soma dos turnos do caso, sem abrir servidores e índice. Uma rodada por modelo.", "",
             "| Modelo | Acerto | Latência média por caso | Custo total (10 casos) | Tokens entrada / saída |",
             "|---|---|---|---|---|"]
    per_model = {path.stem: json.loads(path.read_text()) for path in sorted(RESULTS.glob("*.json"))}
    for model, rows in per_model.items():
        passed = sum(r["passed"] for r in rows)
        seconds = sum(r["seconds"] for r in rows) / len(rows)
        cost = sum(r["cost_usd"] for r in rows)
        tokens_in, tokens_out = sum(r["input_tokens"] for r in rows), sum(r["output_tokens"] for r in rows)
        lines.append(f"| `{model}` | {passed}/{len(rows)} | {seconds:.1f} s | US$ {cost:.4f} | {tokens_in:,} / {tokens_out:,} |")
    for model, rows in per_model.items():
        lines += ["", f"## `{model}`", "", "| # | Caso | Componente | Ferramentas e skills | Aprovado | Tempo | Observação |",
                  "|---|---|---|---|---|---|---|"]
        for r in rows:
            used = sorted({t for turn in r["tools"] for t in turn}) + [f"skill {s}" for turn in r["skills"] for s in turn]
            note = observation(r)
            lines.append(f"| {r['id']} | {r['title']}{' (desafiador)' if r['challenging'] else ''} | {r['component']} | "
                         f"{', '.join(f'`{u}`' for u in used) or '-'} | {'sim' if r['passed'] else 'não'} | "
                         f"{r['seconds']} s | {note.replace('|', '/')} |")
        lines += ["", "<details><summary>Respostas completas</summary>", ""]
        for r in rows:
            lines += [f"### {r['id']}. {r['title']}", ""]
            for text, answer in zip(r["input"], r["answers"] or [""] * len(r["input"])):
                lines += [f"**Usuário:** {text}", "", f"**Assistente:** {answer}", ""]
        lines += ["</details>"]
    (ROOT / "evals" / "RESULTADOS.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True, help="modelo sem o prefixo do provedor")
    parser.add_argument("--case", action="append", type=int, help="roda só estes casos e mescla no resultado")
    args = parser.parse_args()
    from dotenv import load_dotenv
    from langchain.chat_models import init_chat_model

    load_dotenv(ROOT / ".env")
    judge_model = init_chat_model(JUDGE_MODEL, temperature=0).with_structured_output(Verdict)
    for model in args.model:
        run_model(model, judge_model, set(args.case or []))
    write_report()


if __name__ == "__main__":
    main()
