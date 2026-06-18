"""Потолок глубины поиска для силы движка. Чистая логика, без I/O.

Формула снята с Rapfi SkillMovePicker (engine/rapfi/Rapfi/search/skill.h:35-43):
BaseDepth=4, FullDepth=16, Alpha=0.5 → k=(16-4)/(0.5-1)=-24,
targetDepth = 4 + int(-24*(0.5^(s/100) - 1)) = 4 + floor(24*(1 - 0.5^(s/100))).
strength 0..100 → 4..16. Движок применяет это как потолок поиска только при
strength<100 (при 100 skill выключен); в нашей модели — верх диапазона глубины уровня.
"""


def depth_ceiling(strength: int) -> int:
    return 4 + int(24 * (1 - 0.5 ** (strength / 100)))
