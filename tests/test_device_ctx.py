import contextvars

from aidos.agents.ai_agent import AIAgent
from aidos.core.device_ctx import current_device
from aidos.core.memory import MemoryStore
from aidos.core.tool_registry import ToolRegistry


class EchoClient:
    def chat(self, messages, system=None):
        return f"ok:{len(messages)}"


def _agent(tmp_path):
    return AIAgent(client=EchoClient(), memory=MemoryStore(tmp_path / "m.db"), registry=ToolRegistry(), session_id="local")


def test_default_session_without_device(tmp_path):
    agent = _agent(tmp_path)
    agent.handle("сәлем")
    assert len(agent._memory.get_session("local")) == 2


def test_each_device_has_own_history(tmp_path):
    agent = _agent(tmp_path)

    def ask(device_id, text):
        current_device.set(device_id)
        return agent.handle(text)

    contextvars.copy_context().run(ask, "box-1", "бір")
    contextvars.copy_context().run(ask, "box-1", "екі")
    contextvars.copy_context().run(ask, "box-2", "үш")

    assert len(agent._memory.get_session("device:box-1")) == 4
    assert len(agent._memory.get_session("device:box-2")) == 2
    assert agent._memory.get_session("local") == []
