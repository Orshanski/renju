"""Игровая логика партии: валидация хода, усечение undo. Чистые функции."""

from collections.abc import Sequence

from .errors import MoveRejected, MoveRejectReason, UndoRejected, UndoRejectReason
from .values import BOARD_SIZE, Color, Point


def validate_move(*, moves: Sequence[Point], point: Point) -> None:
    """Бросает MoveRejected при нарушении ЦЕЛОСТНОСТИ хода: геометрия → занятость.

    Дебютную зону и фолы НЕ сторожит: для человека их закрывает фронт (рисует только
    разрешённые клетки + forbidden), движок их соблюдает сам (RULE 4). Серверный сторож
    этих правил защищал бы от несуществующей угрозы (self-hosted, свои люди, нет PvP/
    ставок — подделка хода вредит лишь самому игроку). Зона и фолы остаются ПОСТАВЩИКАМИ
    ограничений фронту (opening_zone, GameService.fouls), а не сторожем. Завершённость —
    оркестрация (apply_move), не здесь. Сторона-на-ходу из len(moves); роль не нужна."""
    x, y = point
    if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
        raise MoveRejected(MoveRejectReason.OUT_OF_BOARD)
    if point in set(moves):
        raise MoveRejected(MoveRejectReason.OCCUPIED)


def undo_truncate(*, moves: Sequence[Point], for_color: Color, preset: int = 1) -> list[Point]:
    """Усечь ходы до предыдущего состояния «ход for_color», не снимая preset
    стартовых камней (центр предзаполнен). Новая длина k — наибольшая
    preset ≤ k < len(moves) c очередью for_color (k чётно для чёрных, нечётно для белых).
    Если такого k нет — NOTHING_TO_UNDO. (for_color — сторона, для которой откат;
    источник хода — человек/ИИ — не важен.)"""
    target_parity = 0 if for_color is Color.BLACK else 1
    k = len(moves) - 1
    while k >= preset and k % 2 != target_parity:
        k -= 1
    if k < preset:
        raise UndoRejected(UndoRejectReason.NOTHING_TO_UNDO)
    return list(moves[:k])
