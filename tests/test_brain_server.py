import asyncio

import grpc
import pytest

from aidos.brain.gen import link_pb2, link_pb2_grpc
from aidos.brain.server import BrainService, start_server
from aidos.brain.turn import TurnRunner

TOKEN = "secret"


def _runner(respond=lambda t: "Сәлем, қалайсыз? Бүгін күн жақсы."):
    return TurnRunner(transcribe=lambda a: "сәлем", respond=respond, synthesize=lambda s: (b"\x00\x00" * 10, 22050))


async def _open(service, token=TOKEN):
    server, port = await start_server(service, "127.0.0.1:0")
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    stub = link_pb2_grpc.BrainStub(channel)
    outbox: asyncio.Queue = asyncio.Queue()

    async def requests():
        while True:
            item = await outbox.get()
            if item is None:
                return
            yield item

    call = stub.Link(requests(), metadata=(("authorization", f"Bearer {token}"),))
    return server, channel, call, outbox


def _utt(turn_id="t1"):
    return link_pb2.GatewayEvent(
        utterance=link_pb2.Utterance(device_id="box-1", turn_id=turn_id, pcm_s16le=b"\x10\x00" * 1600, sample_rate=16000)
    )


async def _read_until_end(call):
    events = []
    while (ev := await call.read()) is not grpc.aio.EOF:
        events.append(ev)
        if ev.WhichOneof("kind") == "end":
            return events
    return events


async def test_turn_roundtrip():
    server, channel, call, outbox = await _open(BrainService(_runner(), TOKEN))
    try:
        await outbox.put(_utt())
        events = await asyncio.wait_for(_read_until_end(call), 5)
        assert [e.WhichOneof("kind") for e in events] == ["transcript", "speech", "speech", "end"]
        assert events[-1].end.error is False
    finally:
        await outbox.put(None)
        await channel.close()
        await server.stop(None)


async def test_wrong_token_rejected():
    server, channel, call, outbox = await _open(BrainService(_runner(), TOKEN), token="bad")
    try:
        with pytest.raises(grpc.aio.AioRpcError) as err:
            await asyncio.wait_for(call.read(), 5)
        assert err.value.code() == grpc.StatusCode.UNAUTHENTICATED
    finally:
        await channel.close()
        await server.stop(None)


async def test_abort_cancels_turn():
    started = asyncio.Event()
    release = asyncio.Event()
    loop = asyncio.get_running_loop()

    def slow_respond(text):
        loop.call_soon_threadsafe(started.set)
        asyncio.run_coroutine_threadsafe(release.wait(), loop).result(5)
        return "Кеш жауап."

    server, channel, call, outbox = await _open(BrainService(_runner(slow_respond), TOKEN))
    try:
        await outbox.put(_utt("slow"))
        first = await asyncio.wait_for(call.read(), 5)
        assert first.WhichOneof("kind") == "transcript"
        await asyncio.wait_for(started.wait(), 5)
        await outbox.put(link_pb2.GatewayEvent(abort=link_pb2.Abort(device_id="box-1", turn_id="slow")))
        await asyncio.sleep(0.2)
        release.set()

        await outbox.put(_utt("next"))
        events = await asyncio.wait_for(_read_until_end(call), 5)
        assert {getattr(e, e.WhichOneof("kind")).turn_id for e in events} == {"next"}
    finally:
        await outbox.put(None)
        await channel.close()
        await server.stop(None)


def test_empty_token_rejected():
    with pytest.raises(ValueError):
        BrainService(_runner(), "")


class _Ctx:
    def invocation_metadata(self):
        return (("authorization", f"Bearer {TOKEN}"),)

    async def send_initial_metadata(self, md):
        pass

    async def abort(self, code, details):
        raise AssertionError(details)


class _Gateway:
    """Drives BrainService.Link directly, without a network, so event ordering is deterministic."""

    def __init__(self, runner):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.link = BrainService(runner, TOKEN).Link(self._requests(), _Ctx())

    async def _requests(self):
        while (item := await self.inbox.get()) is not None:
            yield item

    async def send(self, ev):
        await self.inbox.put(ev)

    async def next(self):
        return await asyncio.wait_for(self.link.__anext__(), 5)

    async def close(self):
        await self.inbox.put(None)
        await self.link.aclose()


def _ev(kind, turn_id, **kw):
    return link_pb2.BrainEvent(**{kind: getattr(link_pb2, {"transcript": "Transcript", "speech": "SpeechChunk", "end": "TurnEnd"}[kind])(device_id="box-1", turn_id=turn_id, **kw)})


async def test_abort_drops_already_queued_events():
    emitted, cancelled = asyncio.Event(), asyncio.Event()

    class Runner:
        async def run(self, utt):
            yield _ev("transcript", utt.turn_id, text="x")
            if utt.turn_id != "slow":
                yield _ev("end", utt.turn_id)
                return
            yield _ev("speech", utt.turn_id, text="stale")
            emitted.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    gw = _Gateway(Runner())
    try:
        await gw.send(_utt("slow"))
        assert (await gw.next()).WhichOneof("kind") == "transcript"
        await asyncio.wait_for(emitted.wait(), 5)
        await gw.send(link_pb2.GatewayEvent(abort=link_pb2.Abort(device_id="box-1", turn_id="slow")))
        await asyncio.wait_for(cancelled.wait(), 5)

        await gw.send(_utt("next"))
        ev = await gw.next()
        assert getattr(ev, ev.WhichOneof("kind")).turn_id == "next"
    finally:
        await gw.close()


async def test_finished_turn_does_not_unregister_newer_turn_with_same_id():
    first_done, release_first, second_started, cancelled = (asyncio.Event() for _ in range(4))
    calls = []

    class Runner:
        async def run(self, utt):
            calls.append(1)
            if len(calls) == 1:
                yield _ev("end", utt.turn_id)
                await release_first.wait()
                first_done.set()
                return
            yield _ev("transcript", utt.turn_id, text="second")
            second_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    gw = _Gateway(Runner())
    try:
        await gw.send(_utt("dup"))
        assert (await gw.next()).WhichOneof("kind") == "end"
        await gw.send(_utt("dup"))
        assert (await gw.next()).WhichOneof("kind") == "transcript"
        release_first.set()
        await asyncio.wait_for(first_done.wait(), 5)
        for _ in range(5):
            await asyncio.sleep(0)

        await gw.send(link_pb2.GatewayEvent(abort=link_pb2.Abort(device_id="box-1", turn_id="dup")))
        await asyncio.wait_for(cancelled.wait(), 5)
    finally:
        await gw.close()


async def test_request_stream_error_ends_link_cleanly():
    async def broken():
        raise RuntimeError("boom")
        yield

    link = BrainService(_runner(), TOKEN).Link(broken(), _Ctx())
    assert [e async for e in link] == []
