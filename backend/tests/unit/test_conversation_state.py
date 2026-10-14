import pytest

from justai.conversation.echo_filter import EchoTranscriptFilter
from justai.conversation.state import InvalidTransition, SessionState as S, StateMachine


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_happy_path_and_listeners() -> None:
    clock = Clock()
    sm = StateMachine(10, clock)
    seen: list[tuple[S, S]] = []
    sm.on_change(lambda a, b, r: seen.append((a, b)))
    for target in (S.STARTING, S.LISTENING, S.PROCESSING, S.SPEAKING, S.LISTENING, S.ENDED):
        sm.transition(target)
    assert seen[-1] == (S.LISTENING, S.ENDED)
    with pytest.raises(InvalidTransition):
        sm.transition(S.LISTENING)


def test_invalid_transition() -> None:
    sm = StateMachine(10)
    with pytest.raises(InvalidTransition):
        sm.transition(S.SPEAKING)


def test_timeout_only_while_listening() -> None:
    clock = Clock()
    sm = StateMachine(10, clock)
    sm.transition(S.STARTING)
    sm.transition(S.LISTENING)
    clock.t = 5
    sm.transition(S.PROCESSING)
    clock.t = 30  # long processing / speaking never times out
    assert not sm.timed_out()
    sm.transition(S.SPEAKING)
    clock.t = 60
    assert not sm.timed_out()
    sm.transition(S.LISTENING)  # timer restarts when listening again
    clock.t = 69.9
    assert not sm.timed_out()
    clock.t = 70.0
    assert sm.timed_out()


def test_user_speech_and_echo_window_postpone_timeout() -> None:
    clock = Clock()
    sm = StateMachine(10, clock)
    sm.transition(S.STARTING)
    sm.transition(S.LISTENING)
    clock.t = 8
    sm.activity()  # user speaks
    clock.t = 17
    assert not sm.timed_out()
    sm.activity(at=25)  # echo window of the last answer closes only at t=25
    clock.t = 34
    assert not sm.timed_out()
    clock.t = 35
    assert sm.timed_out()


def test_echo_filter_detects_own_speech() -> None:
    clock = Clock()
    f = EchoTranscriptFilter(clock=clock)
    f.assistant_said("Morgen wird das Wetter voraussichtlich sonnig, mit bis zu 24 Grad.")
    assert f.is_echo("das wetter voraussichtlich sonnig mit bis zu 24 grad")
    assert not f.is_echo("Stopp, ich meinte heute")
    assert not f.is_echo("ja")  # too short to judge
    clock.t = 100
    assert not f.is_echo("das wetter voraussichtlich sonnig")  # outside the window


def test_echo_filter_handles_umlauts_and_punctuation() -> None:
    f = EchoTranscriptFilter()
    f.assistant_said("Möchtest du, dass ich dich registriere?")
    assert f.is_echo("mochtest du dass ich dich registriere")
