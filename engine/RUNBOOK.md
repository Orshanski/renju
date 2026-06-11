# Rapfi — развёртывание движка с нуля

Движок собирается НА ЦЕЛЕВОМ ХОСТЕ под его CPU. Перенос готового бинаря
между разными CPU ломается на нелегальных инструкциях (SIGILL).

## Шаги

1. Получить исходники (каталог `engine/rapfi` гитигнорится — это локальный
   клон, в git проекта он не входит; пин — проверенный коммит):

       git clone https://github.com/dhbloo/rapfi.git engine/rapfi
       git -C engine/rapfi checkout 3aedf3a2ab0ab710a9f3d00e57d5287ceb864894
       git -C engine/rapfi submodule update --init Networks   # NNUE-веса (~50 МБ)

2. Собрать (нужны cmake и компилятор C++17: Apple clang / gcc):

       engine/build.sh

   Бинарь: `engine/rapfi/Rapfi/build/native/pbrain-rapfi`.
   SIMD-флаги CMake выбирает автоматически под CPU хоста.

3. Smoke-проверка (из корня репо; ожидается ход вида `x,y` последней строкой,
   в MESSAGE-строках — `mix9svq nnue: weight loaded`):

       printf 'START 15\nINFO rule 4\nINFO timeout_turn 2000\nBOARD\n7,7,2\nDONE\nEND\n' \
         | engine/rapfi/Rapfi/build/native/pbrain-rapfi --config engine/config.toml

## Конфиг

`engine/config.toml` — скопирован из `Networks/config-example/config.toml`,
пути весов исправлены на `rapfi/Networks/...` (резолвятся относительно каталога
конфига). Эвалюатор: `mix9svq`, рэндзю-веса парой black/white. Важные
зафиксированные значения: `coord_conversion_mode = "none"` (координаты x,y
как в протоколе, без конверсий — на это рассчитан парсер адаптера) и
`default_thread_num = 1`.

## Как бэкенд находит бинарь

`app/config.py`: env `RENJU_RAPFI_BIN`, иначе самый свежий по mtime
`engine/rapfi/Rapfi/build/*/pbrain-rapfi`. Конфиг: env `RENJU_RAPFI_CONFIG`,
иначе `engine/config.toml`.
