#!/usr/bin/env bash
# Сборка Rapfi из engine/rapfi под CPU текущей машины.
# SIMD-расширения (NEON/DOTPROD/AVX2/…) CMakeLists определяет сам.
# ВАЖНО: бинарь НЕ переносим между разными CPU — на каждом хосте своя сборка (иначе SIGILL).
set -euo pipefail
cd "$(dirname "$0")/rapfi/Rapfi"
cmake -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native -j
echo "OK: $(pwd)/build/native/pbrain-rapfi"
