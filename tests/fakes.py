"""Modelos e ferramentas falsos para testar o grafo sem rede."""

from __future__ import annotations

import inspect
from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import StructuredTool
from pydantic import Field


class ScriptedModel(BaseChatModel):
    """Devolve as respostas da lista, em ordem, e guarda as mensagens que recebeu."""

    responses: list[AIMessage]
    calls: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(list(messages))
        reply = self.responses.pop(0)
        return ChatResult(generations=[ChatGeneration(message=reply.model_copy())])

    def system_prompt(self, call: int = -1) -> str:
        return self.calls[call][0].content


def call(name: str, **args) -> AIMessage:
    """Resposta do modelo pedindo uma ferramenta."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c-{name}-{id(args)}"}])


def say(text: str) -> AIMessage:
    return AIMessage(content=text)


def make_tool(name: str, func: Callable[..., Any]) -> StructuredTool:
    """Ferramenta a partir de uma função comum, registrando os argumentos em .received."""
    received: list[dict] = []

    def wrapper(**kwargs):
        received.append(kwargs)
        return func(**kwargs)

    wrapper.__signature__ = inspect.signature(func)
    wrapper.__annotations__ = func.__annotations__
    tool = StructuredTool.from_function(func=wrapper, name=name, description=f"ferramenta {name}")
    tool.metadata = {"received": received}
    return tool


def verdict(value) -> RunnableLambda:
    """Classificador falso que sempre devolve o mesmo veredito e guarda os prompts recebidos."""
    prompts: list[str] = []

    def run(prompt):
        prompts.append(prompt)
        return value

    runnable = RunnableLambda(run)
    runnable.prompts = prompts
    return runnable
