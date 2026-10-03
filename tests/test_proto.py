from aidos.brain.gen import link_pb2, link_pb2_grpc


def test_roundtrip_utterance():
    ev = link_pb2.GatewayEvent(
        utterance=link_pb2.Utterance(device_id="d1", turn_id="t1", pcm_s16le=b"\x01\x00", sample_rate=16000)
    )
    parsed = link_pb2.GatewayEvent.FromString(ev.SerializeToString())
    assert parsed.WhichOneof("kind") == "utterance"
    assert parsed.utterance.sample_rate == 16000


def test_service_is_generated():
    assert hasattr(link_pb2_grpc, "BrainServicer")
    assert hasattr(link_pb2_grpc, "BrainStub")
