"""gRPC мозг-сервері: шлюзбен бір Link ағыны арқылы сөйлеседі."""

from __future__ import annotations

import asyncio
import hmac
import logging

import grpc

from aidos.brain.gen import link_pb2, link_pb2_grpc
from aidos.brain.turn import TurnRunner

_log = logging.getLogger("aidos.brain.server")


class BrainService(link_pb2_grpc.BrainServicer):
    def __init__(self, runner: TurnRunner, token: str) -> None:
        if not token:
            raise ValueError("LINK_TOKEN is empty")
        self._runner = runner
        self._token = token

    async def Link(self, request_iterator, context):
        """Шлюз Link-ті өз өмірінде ашық ұстайды: сұраныс ағынын жабу байланысты аяқтап, ұшып жатқан жүрістерді тоқтатады."""
        metadata = dict(context.invocation_metadata())
        supplied = str(metadata.get("authorization", ""))
        if not hmac.compare_digest(supplied.encode(), f"Bearer {self._token}".encode()):
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "bad link token")
        # Python aio initial metadata-ны бірінші хабарламаға дейін жібермейді, ал tonic клиенті
        # link().await-те соны күтеді — жібермесе, екі жақ та бір-бірін күтіп қалады.
        await context.send_initial_metadata(())

        out: asyncio.Queue[link_pb2.BrainEvent | None] = asyncio.Queue()
        turns: dict[str, asyncio.Task] = {}
        aborted: set[str] = set()
        reader = asyncio.create_task(self._read(request_iterator, out, turns, aborted))
        _log.info("Шлюз қосылды")
        try:
            while (event := await out.get()) is not None:
                kind = event.WhichOneof("kind")
                if getattr(getattr(event, kind), "turn_id", None) in aborted:
                    continue
                yield event
        finally:
            reader.cancel()
            for task in turns.values():
                task.cancel()
            _log.info("Шлюз ажыратылды")

    async def _read(
        self, request_iterator, out: asyncio.Queue, turns: dict[str, asyncio.Task], aborted: set[str]
    ) -> None:
        try:
            async for event in request_iterator:
                kind = event.WhichOneof("kind")
                if kind == "utterance":
                    utt = event.utterance
                    aborted.discard(utt.turn_id)
                    turns[utt.turn_id] = asyncio.create_task(self._run_turn(utt, out, turns))
                elif kind == "abort":
                    aborted.add(event.abort.turn_id)
                    task = turns.pop(event.abort.turn_id, None)
                    if task:
                        task.cancel()
                        _log.info("Ход тоқтатылды: %s", event.abort.turn_id)
                elif kind == "state":
                    _log.info("Колонка %s: online=%s", event.state.device_id, event.state.online)
                elif kind == "push_ack":
                    _log.debug("PushAck: %s", event.push_ack.push_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("Link оқу қатесі: %s", exc)
        finally:
            await out.put(None)

    async def _run_turn(self, utt: link_pb2.Utterance, out: asyncio.Queue, turns: dict[str, asyncio.Task]) -> None:
        try:
            async for event in self._runner.run(utt):
                await out.put(event)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _log.error("Ход қатесі (turn=%s): %s", utt.turn_id, exc)
            await out.put(link_pb2.BrainEvent(
                end=link_pb2.TurnEnd(device_id=utt.device_id, turn_id=utt.turn_id, error=True)
            ))
        finally:
            if turns.get(utt.turn_id) is asyncio.current_task():
                del turns[utt.turn_id]


async def start_server(service: BrainService, bind: str) -> tuple[grpc.aio.Server, int]:
    server = grpc.aio.server()
    link_pb2_grpc.add_BrainServicer_to_server(service, server)
    port = server.add_insecure_port(bind)
    await server.start()
    _log.info("Мозг тыңдауда: %s (port=%d)", bind, port)
    return server, port


async def serve(service: BrainService, bind: str) -> None:
    server, _ = await start_server(service, bind)
    await server.wait_for_termination()
