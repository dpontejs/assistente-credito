"""Grafo do assistente: guarda de entrada → perfil → agente ⇄ ferramentas (com RAG agêntico) → guarda de saída."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command

from credito.guards import INPUT_GUARD_PROMPT, OUTPUT_GUARD_PROMPT, REFUSALS, SAFE_OUTPUT, mask_sensitive
from credito.prompts import system_prompt
from credito.rag import grade_chunks, rewrite_query


MAX_TOOL_ROUNDS = 8
BLOCKED_PLACEHOLDER = "[mensagem bloqueada pelo guardrail]"
LIMIT_NOTE = "\n\n# Limite\nVocê já usou ferramentas demais neste turno. Responda agora com o que já tem, sem chamar ferramentas."
LIMIT_FALLBACK = "Não consegui concluir a análise com as ferramentas disponíveis. Pode reformular ou dividir a pergunta?"


class CreditState(MessagesState):
    user_id: str
    owner: str | None
    tool_rounds: int
    profile: str
    rewrites: int
    retry_query: str | None
    search_exhausted: bool
    blocked: str | None


@dataclass
class Deps:
    model: BaseChatModel
    input_guard: Runnable
    output_guard: Runnable
    grader: Runnable
    rewriter: BaseChatModel
    tools: list[BaseTool]
    catalog: str
    profile_tool: str = "credito_get_profile"
    search_tool: str = "search_norms"
    max_rewrites: int = 2


def as_text(content: Any) -> str:
    """Converte o conteúdo de mensagem ou de ferramenta (texto ou lista de blocos) em texto."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return str(content)


def last_human(state: CreditState) -> HumanMessage:
    """A pergunta corrente é a última mensagem do usuário, não a primeira da thread."""
    return next(m for m in reversed(state["messages"]) if isinstance(m, HumanMessage))


def last_tool_batch(state: CreditState) -> tuple[AIMessage, list[ToolMessage]]:
    """A última chamada de ferramentas do agente e as respostas que vieram depois dela."""
    messages = state["messages"]
    index = max(i for i, m in enumerate(messages) if isinstance(m, AIMessage) and m.tool_calls)
    return messages[index], [m for m in messages[index + 1:] if isinstance(m, ToolMessage)]


def build_graph(deps: Deps, checkpointer=None):
    """Monta e compila o grafo com as dependências injetadas."""
    tools = {tool.name: tool for tool in deps.tools}
    model = deps.model.bind_tools(deps.tools)

    async def guard_input(state: CreditState) -> Command[Literal["refuse", "load_profile"]]:
        """Mascara CPF e cartão na mensagem e barra injection, fora de escopo e pedido de dados de terceiros."""
        message = last_human(state)
        update: dict = {"rewrites": 0, "retry_query": None, "search_exhausted": False, "blocked": None,
                        "tool_rounds": 0}
        owner = state.get("owner")
        if owner and owner != state["user_id"]:
            return Command(update={**update, "blocked": "outro_usuario"}, goto="refuse")
        update["owner"] = owner or state["user_id"]
        masked = mask_sensitive(as_text(message.content))
        if masked != message.content:
            update["messages"] = [HumanMessage(masked, id=message.id)]
        verdict = await deps.input_guard.ainvoke(INPUT_GUARD_PROMPT.format(message=masked))
        if verdict.category != "ok":
            return Command(update={**update, "blocked": verdict.category}, goto="refuse")
        return Command(update=update, goto="load_profile")

    def refuse(state: CreditState) -> dict:
        """Troca a mensagem barrada por um marcador (para não voltar ao modelo depois) e responde com a recusa fixa."""
        placeholder = HumanMessage(BLOCKED_PLACEHOLDER, id=last_human(state).id)
        return {"messages": [placeholder, AIMessage(REFUSALS[state["blocked"]])]}

    async def load_profile(state: CreditState) -> dict:
        """Lê o perfil do usuário ativo no servidor MCP; é isso que faz o agente lembrar entre conversas."""
        tool = tools.get(deps.profile_tool)
        if tool is None:
            return {"profile": ""}
        try:
            text = as_text(await tool.ainvoke({"user_id": state["user_id"]}))
        except Exception:  # perfil indisponível não impede a conversa
            return {"profile": ""}
        return {"profile": "" if text.startswith("erro") else text}

    async def agent(state: CreditState) -> dict:
        """Decide se responde, chama ferramentas ou carrega uma skill."""
        prompt = system_prompt(state.get("profile", ""), deps.catalog, state.get("retry_query"),
                               state.get("search_exhausted", False))
        if state.get("tool_rounds", 0) < MAX_TOOL_ROUNDS:
            return {"messages": [await model.ainvoke([SystemMessage(prompt), *state["messages"]])]}
        # no limite, o modelo responde sem ferramentas; uma chamada que escape é descartada
        response = await deps.model.ainvoke([SystemMessage(prompt + LIMIT_NOTE), *state["messages"]])
        if response.tool_calls:
            response = AIMessage(as_text(response.content) or LIMIT_FALLBACK)
        return {"messages": [response]}

    async def run_tool(call: dict, user_id: str) -> ToolMessage:
        """Executa uma chamada, trocando o user_id pelo do estado e convertendo falhas em texto."""
        tool = tools.get(call["name"])
        args = dict(call["args"])
        if tool is None:
            content = f"erro: ferramenta {call['name']} não existe"
        else:
            if "user_id" in tool.args:
                args["user_id"] = user_id
            else:
                args.pop("user_id", None)  # o modelo às vezes repete o user_id em ferramentas que não o têm
            try:
                content = as_text(await tool.ainvoke(args))
            except Exception as error:  # a falha vira resposta para o modelo, não derruba o grafo
                content = f"erro: {error}"
        return ToolMessage(content=content, tool_call_id=call["id"], name=call["name"])

    async def run_tools(state: CreditState) -> dict:
        """Executa em paralelo as ferramentas pedidas pelo agente."""
        calls = state["messages"][-1].tool_calls
        results = await asyncio.gather(*(run_tool(call, state["user_id"]) for call in calls))
        return {"messages": list(results), "tool_rounds": state.get("tool_rounds", 0) + 1}

    async def grade(state: CreditState) -> Command[Literal["agent", "rewrite"]]:
        """Avalia se os trechos das normas respondem; senão manda reescrever, até o limite."""
        _, results = last_tool_batch(state)
        context = "\n\n".join(m.content for m in results if m.name == deps.search_tool)
        question = as_text(last_human(state).content)
        if await asyncio.to_thread(grade_chunks, question, context, deps.grader):
            return Command(update={"retry_query": None}, goto="agent")
        if state.get("rewrites", 0) >= deps.max_rewrites:
            return Command(update={"retry_query": None, "search_exhausted": True}, goto="agent")
        return Command(goto="rewrite")

    async def rewrite(state: CreditState) -> dict:
        """Reformula a pergunta com os termos das normas para a próxima busca."""
        query = await asyncio.to_thread(rewrite_query, as_text(last_human(state).content), deps.rewriter)
        return {"retry_query": query, "rewrites": state.get("rewrites", 0) + 1}

    async def guard_output(state: CreditState) -> dict:
        """Mascara dados sensíveis e troca respostas com investimento específico ou garantia de aprovação."""
        answer = state["messages"][-1]
        text = as_text(answer.content)
        verdict = await deps.output_guard.ainvoke(OUTPUT_GUARD_PROMPT.format(answer=text))
        if verdict.investment_advice or verdict.approval_guarantee:
            return {"messages": [AIMessage(SAFE_OUTPUT, id=answer.id)]}
        masked = mask_sensitive(text)
        if masked != text:
            return {"messages": [AIMessage(masked, id=answer.id)]}
        return {}

    def after_agent(state: CreditState) -> Literal["tools", "guard_output"]:
        return "tools" if state["messages"][-1].tool_calls else "guard_output"

    def after_tools(state: CreditState) -> Literal["grade", "agent"]:
        call_message, _ = last_tool_batch(state)
        searched = any(call["name"] == deps.search_tool for call in call_message.tool_calls)
        return "grade" if searched else "agent"

    builder = StateGraph(CreditState)

    # nós
    builder.add_node("guard_input", guard_input)
    builder.add_node("refuse", refuse)
    builder.add_node("load_profile", load_profile)
    builder.add_node("agent", agent)
    builder.add_node("tools", run_tools)
    builder.add_node("grade", grade)
    builder.add_node("rewrite", rewrite)
    builder.add_node("guard_output", guard_output)

    # arestas
    builder.add_edge(START, "guard_input")
    builder.add_edge("refuse", END)
    builder.add_edge("load_profile", "agent")
    builder.add_conditional_edges("agent", after_agent, ["tools", "guard_output"])
    builder.add_conditional_edges("tools", after_tools, ["grade", "agent"])
    builder.add_edge("rewrite", "agent")
    builder.add_edge("guard_output", END)

    return builder.compile(checkpointer=checkpointer)
