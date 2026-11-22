"""Mantém o assistente assíncrono vivo numa thread própria e oferece chamadas síncronas ao Streamlit.

O Streamlit reexecuta o script a cada interação; os servidores MCP e o checkpointer
precisam ficar abertos entre as reexecuções, num único loop de eventos.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import AbstractAsyncContextManager
from typing import Callable

from langchain_core.messages import BaseMessage, HumanMessage


def _default_factory() -> AbstractAsyncContextManager:
    from credito.assistant import open_assistant

    return open_assistant()


class AssistantRunner:
    """Abre o assistente uma vez numa thread de fundo e repassa as chamadas para o loop dela."""

    def __init__(self, factory: Callable[[], AbstractAsyncContextManager] = _default_factory, timeout: float = 180):
        self.timeout = timeout
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._assistant = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._loop.run_until_complete, args=(self._main(factory),),
                                        daemon=True, name="assistant-runner")
        self._thread.start()

    async def _main(self, factory) -> None:
        self._stop = asyncio.Event()
        try:
            async with factory() as assistant:
                self._assistant = assistant
                self._ready.set()
                await self._stop.wait()
        except BaseException as error:  # guardado para relançar na thread de quem chamou
            self._error = error
        finally:
            self._ready.set()

    @property
    def error(self) -> BaseException | None:
        """Erro da abertura do assistente, se houve; o app usa para descartar o runner e tentar de novo."""
        return self._error

    def _run(self, coroutine_factory):
        if not self._ready.wait(self.timeout):
            raise TimeoutError("o assistente ainda está abrindo; tente de novo em instantes")
        if self._error is not None:
            raise self._error
        future = asyncio.run_coroutine_threadsafe(coroutine_factory(self._assistant.graph), self._loop)
        try:
            return future.result(self.timeout)
        except TimeoutError:
            future.cancel()  # sem isso o turno seguiria rodando e disputaria a mesma thread com o próximo
            raise TimeoutError(f"o assistente demorou mais de {self.timeout:.0f} s para responder") from None

    def ask(self, user_id: str, thread_id: str, text: str) -> list[BaseMessage]:
        """Envia uma mensagem e devolve todas as mensagens da thread depois do turno."""
        config = {"configurable": {"thread_id": thread_id}}

        async def run(graph):
            state = await graph.ainvoke({"messages": [HumanMessage(text)], "user_id": user_id}, config)
            return state["messages"]

        return self._run(run)

    def history(self, thread_id: str) -> list[BaseMessage]:
        """Mensagens já guardadas no checkpointer para a thread."""
        config = {"configurable": {"thread_id": thread_id}}

        async def run(graph):
            snapshot = await graph.aget_state(config)
            return snapshot.values.get("messages", [])

        return self._run(run)

    def close(self) -> None:
        """Fecha o assistente (e os servidores MCP) e encerra a thread."""
        self._ready.wait(self.timeout)  # espera a abertura terminar para não perder o sinal de parada
        if self._stop is not None and self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=30)
