import pytest

from app.rapfi.process import EngineProcessDied, RapfiProcess


async def test_spawn_about_and_terminate(rapfi_paths):
    bin_path, config_path, cwd = rapfi_paths
    proc = await RapfiProcess.spawn(bin_path=bin_path, config_path=config_path, cwd=cwd)
    try:
        assert proc.alive
        await proc.send(["ABOUT"])
        line = await proc.read_line()
        while 'name="Rapfi"' not in line:  # пропустить MESSAGE о загрузке конфига
            line = await proc.read_line()
        assert 'name="Rapfi"' in line
    finally:
        await proc.terminate(grace_s=2.0)
    assert not proc.alive


async def test_pid_exposed_after_spawn(rapfi_paths):
    bin_path, config_path, cwd = rapfi_paths
    proc = await RapfiProcess.spawn(bin_path=bin_path, config_path=config_path, cwd=cwd)
    try:
        assert isinstance(proc.pid, int) and proc.pid > 0
    finally:
        await proc.terminate(grace_s=2.0)


async def test_read_after_death_raises(rapfi_paths):
    bin_path, config_path, cwd = rapfi_paths
    proc = await RapfiProcess.spawn(bin_path=bin_path, config_path=config_path, cwd=cwd)
    await proc.send(["END"])  # штатное завершение по протоколу
    with pytest.raises(EngineProcessDied):
        # дочитываем возможный хвост; после EOF обязан брошен EngineProcessDied
        for _ in range(100):
            await proc.read_line()
    await proc.terminate(grace_s=2.0)
    assert not proc.alive
