import contextvars

from aidos.agents import music_agent
from aidos.agents.music_agent import MusicAgent
from aidos.core.device_ctx import DeviceAction, current_device, emit_action, turn_actions


def _no_popen(*args, **kwargs):
    raise AssertionError("Popen шақырылмауы керек")


def test_play_on_device_emits_action(monkeypatch):
    monkeypatch.setattr(music_agent, "_get_stream_url", lambda q: ("https://x/a", "Song"))
    monkeypatch.setattr(music_agent.subprocess, "Popen", _no_popen)
    actions: list[DeviceAction] = []

    def scenario():
        current_device.set("box-1")
        turn_actions.set(actions)
        return MusicAgent().handle("Димаш ойна")

    assert contextvars.copy_context().run(scenario) == "Ойнатылуда: Song"
    assert actions == [DeviceAction("play", "https://x/a", "Song")]


def test_play_not_found_on_device(monkeypatch):
    monkeypatch.setattr(music_agent, "_get_stream_url", lambda q: None)
    monkeypatch.setattr(music_agent.subprocess, "Popen", _no_popen)
    actions: list[DeviceAction] = []

    def scenario():
        current_device.set("box-1")
        turn_actions.set(actions)
        return MusicAgent().handle("Димаш ойна")

    assert contextvars.copy_context().run(scenario) == "Музыка табылмады."
    assert actions == []


def test_stop_pause_resume_on_device(monkeypatch):
    monkeypatch.setattr(music_agent.subprocess, "Popen", _no_popen)
    actions: list[DeviceAction] = []
    replies = []

    def scenario():
        current_device.set("box-1")
        turn_actions.set(actions)
        agent = MusicAgent()
        for query in ("тоқтат", "кідірт", "жалғастыр"):
            replies.append(agent.handle(query))

    contextvars.copy_context().run(scenario)
    assert replies == ["Музыка тоқтатылды.", "Музыка кідіртілді.", "Музыка жалғастырылды."]
    assert actions == [DeviceAction("stop"), DeviceAction("pause"), DeviceAction("resume")]


def test_emit_action_without_turn_returns_false():
    assert emit_action("stop") is False


def test_no_device_uses_ffplay(monkeypatch):
    popen_calls = []

    class FakeProc:
        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            pass

        def kill(self):
            pass

    def fake_popen(cmd, **kwargs):
        popen_calls.append(cmd)
        return FakeProc()

    monkeypatch.setattr(music_agent, "_get_stream_url", lambda q: ("https://x/a", "Song"))
    monkeypatch.setattr(music_agent.subprocess, "Popen", fake_popen)

    def scenario():
        assert current_device.get() is None
        agent = MusicAgent()
        reply = agent.handle("Димаш ойна")
        if agent._thread:
            agent._thread.join(timeout=2)
        return reply

    assert contextvars.copy_context().run(scenario) == "Ойнатылуда: Song"
    assert popen_calls and popen_calls[0][0] == "ffplay"
