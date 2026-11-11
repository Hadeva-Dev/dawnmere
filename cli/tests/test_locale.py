"""A Terminal whose locale is not UTF-8 (GB2312, Shift-JIS, Latin-1): every file is still read and written as UTF-8."""
import os
import subprocess
import sys

import pytest

LEGACY = "zh_CN.GB2312"
# main() run as the command is (no argv passed), with doctor swapped for a line that reads config.toml
RUN = ("import sys; from lflabs_memory_cli import main, settings; "
       "main.COMMANDS['doctor'] = (lambda a: print(settings.load().get('owner_name')) or 0, ''); "
       "sys.argv = ['dawnmere', 'doctor']; sys.exit(main.main())")


def has_locale(name):
    try:
        return name in subprocess.run(["locale", "-a"], capture_output=True, text=True, timeout=10).stdout.split()
    except OSError:
        return False


@pytest.mark.skipif(not has_locale(LEGACY), reason=f"this machine has no {LEGACY} locale")
def test_config_with_a_name_the_locale_cannot_read(tmp_path):
    """config.toml holding a Japanese name was a UnicodeDecodeError traceback in setup and doctor under GB2312."""
    (tmp_path / "config.toml").write_text('version = 1\nowner_name = "山田"\n', encoding="utf-8")
    env = {**os.environ, "LFLABS_MEMORY_HOME": str(tmp_path), "LC_ALL": LEGACY, "LANG": LEGACY}
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)
    r = subprocess.run([sys.executable, "-c", RUN], env=env, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode(errors="replace")
    assert r.stdout.decode("utf-8").strip() == "山田"  # a pipe, not a Terminal: UTF-8, as the files are


def test_a_utf8_locale_is_left_alone(monkeypatch):
    from lflabs_memory_cli import main
    monkeypatch.setattr(main.locale, "getencoding", lambda: "UTF-8")
    monkeypatch.setattr(main.os, "execv", lambda *a: pytest.fail("restarted"))
    main.utf8_everywhere()
