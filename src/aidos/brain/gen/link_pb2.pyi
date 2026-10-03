from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class GatewayEvent(_message.Message):
    __slots__ = ("utterance", "abort", "state", "push_ack")
    UTTERANCE_FIELD_NUMBER: _ClassVar[int]
    ABORT_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    PUSH_ACK_FIELD_NUMBER: _ClassVar[int]
    utterance: Utterance
    abort: Abort
    state: DeviceState
    push_ack: PushAck
    def __init__(self, utterance: _Optional[_Union[Utterance, _Mapping]] = ..., abort: _Optional[_Union[Abort, _Mapping]] = ..., state: _Optional[_Union[DeviceState, _Mapping]] = ..., push_ack: _Optional[_Union[PushAck, _Mapping]] = ...) -> None: ...

class Utterance(_message.Message):
    __slots__ = ("device_id", "turn_id", "pcm_s16le", "sample_rate")
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    PCM_S16LE_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_RATE_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    turn_id: str
    pcm_s16le: bytes
    sample_rate: int
    def __init__(self, device_id: _Optional[str] = ..., turn_id: _Optional[str] = ..., pcm_s16le: _Optional[bytes] = ..., sample_rate: _Optional[int] = ...) -> None: ...

class Abort(_message.Message):
    __slots__ = ("device_id", "turn_id")
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    turn_id: str
    def __init__(self, device_id: _Optional[str] = ..., turn_id: _Optional[str] = ...) -> None: ...

class DeviceState(_message.Message):
    __slots__ = ("device_id", "online")
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    ONLINE_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    online: bool
    def __init__(self, device_id: _Optional[str] = ..., online: _Optional[bool] = ...) -> None: ...

class PushAck(_message.Message):
    __slots__ = ("push_id",)
    PUSH_ID_FIELD_NUMBER: _ClassVar[int]
    push_id: str
    def __init__(self, push_id: _Optional[str] = ...) -> None: ...

class BrainEvent(_message.Message):
    __slots__ = ("transcript", "speech", "action", "end", "push")
    TRANSCRIPT_FIELD_NUMBER: _ClassVar[int]
    SPEECH_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    END_FIELD_NUMBER: _ClassVar[int]
    PUSH_FIELD_NUMBER: _ClassVar[int]
    transcript: Transcript
    speech: SpeechChunk
    action: Action
    end: TurnEnd
    push: Push
    def __init__(self, transcript: _Optional[_Union[Transcript, _Mapping]] = ..., speech: _Optional[_Union[SpeechChunk, _Mapping]] = ..., action: _Optional[_Union[Action, _Mapping]] = ..., end: _Optional[_Union[TurnEnd, _Mapping]] = ..., push: _Optional[_Union[Push, _Mapping]] = ...) -> None: ...

class Transcript(_message.Message):
    __slots__ = ("device_id", "turn_id", "text")
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    turn_id: str
    text: str
    def __init__(self, device_id: _Optional[str] = ..., turn_id: _Optional[str] = ..., text: _Optional[str] = ...) -> None: ...

class SpeechChunk(_message.Message):
    __slots__ = ("device_id", "turn_id", "text", "pcm_s16le", "sample_rate")
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    PCM_S16LE_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_RATE_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    turn_id: str
    text: str
    pcm_s16le: bytes
    sample_rate: int
    def __init__(self, device_id: _Optional[str] = ..., turn_id: _Optional[str] = ..., text: _Optional[str] = ..., pcm_s16le: _Optional[bytes] = ..., sample_rate: _Optional[int] = ...) -> None: ...

class TurnEnd(_message.Message):
    __slots__ = ("device_id", "turn_id", "error")
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    turn_id: str
    error: bool
    def __init__(self, device_id: _Optional[str] = ..., turn_id: _Optional[str] = ..., error: _Optional[bool] = ...) -> None: ...

class Push(_message.Message):
    __slots__ = ("push_id", "device_id", "text", "speech", "created_at_unix")
    PUSH_ID_FIELD_NUMBER: _ClassVar[int]
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    SPEECH_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_UNIX_FIELD_NUMBER: _ClassVar[int]
    push_id: str
    device_id: str
    text: str
    speech: SpeechChunk
    created_at_unix: int
    def __init__(self, push_id: _Optional[str] = ..., device_id: _Optional[str] = ..., text: _Optional[str] = ..., speech: _Optional[_Union[SpeechChunk, _Mapping]] = ..., created_at_unix: _Optional[int] = ...) -> None: ...

class Action(_message.Message):
    __slots__ = ("device_id", "turn_id", "play", "stop", "pause", "resume")
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    TURN_ID_FIELD_NUMBER: _ClassVar[int]
    PLAY_FIELD_NUMBER: _ClassVar[int]
    STOP_FIELD_NUMBER: _ClassVar[int]
    PAUSE_FIELD_NUMBER: _ClassVar[int]
    RESUME_FIELD_NUMBER: _ClassVar[int]
    device_id: str
    turn_id: str
    play: PlayStream
    stop: Empty
    pause: Empty
    resume: Empty
    def __init__(self, device_id: _Optional[str] = ..., turn_id: _Optional[str] = ..., play: _Optional[_Union[PlayStream, _Mapping]] = ..., stop: _Optional[_Union[Empty, _Mapping]] = ..., pause: _Optional[_Union[Empty, _Mapping]] = ..., resume: _Optional[_Union[Empty, _Mapping]] = ...) -> None: ...

class PlayStream(_message.Message):
    __slots__ = ("url", "title")
    URL_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    url: str
    title: str
    def __init__(self, url: _Optional[str] = ..., title: _Optional[str] = ...) -> None: ...

class Empty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
