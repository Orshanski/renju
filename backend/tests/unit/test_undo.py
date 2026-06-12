import pytest

from app.domain.undo import UndoPolicy, check_undo
from app.domain.values import GameStatus, UndoRejected, UndoRejectReason


def policy(**kw) -> UndoPolicy:
    return UndoPolicy(**{"enabled": True, "limit": None, "after_game_end": True, **kw})


def test_default_policy_allows_undo_in_awaiting_move():
    check_undo(policy=policy(), status=GameStatus.AWAITING_MOVE, undo_count=0)


def test_disabled_policy_rejects():
    with pytest.raises(UndoRejected) as e:
        check_undo(policy=policy(enabled=False), status=GameStatus.AWAITING_MOVE, undo_count=0)
    assert e.value.reason is UndoRejectReason.DISABLED


def test_opponent_thinking_rejects():
    with pytest.raises(UndoRejected) as e:
        check_undo(policy=policy(), status=GameStatus.OPPONENT_THINKING, undo_count=0)
    assert e.value.reason is UndoRejectReason.OPPONENT_THINKING


def test_after_game_end_allowed_when_enabled():
    check_undo(policy=policy(), status=GameStatus.FINISHED_BLACK, undo_count=0)


def test_after_game_end_rejected_when_disabled():
    with pytest.raises(UndoRejected) as e:
        check_undo(
            policy=policy(after_game_end=False), status=GameStatus.FINISHED_DRAW, undo_count=0
        )
    assert e.value.reason is UndoRejectReason.GAME_FINISHED


def test_limit_reached_rejects():
    with pytest.raises(UndoRejected) as e:
        check_undo(policy=policy(limit=3), status=GameStatus.AWAITING_MOVE, undo_count=3)
    assert e.value.reason is UndoRejectReason.LIMIT_REACHED


def test_under_limit_allows():
    check_undo(policy=policy(limit=3), status=GameStatus.AWAITING_MOVE, undo_count=2)
