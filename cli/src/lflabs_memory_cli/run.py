"""Running other programs (claude, launchctl, security, uv): found on PATH, so tests put fakes first."""
import subprocess
from dataclasses import dataclass


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self):
        return self.code == 0


def run(argv, input=None, timeout=60, env=None):
    """argv's exit code and output. A missing program is code 127, a timeout 124: never an exception."""
    try:
        p = subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL if input is None else None)
        return Result(p.returncode, p.stdout, p.stderr)
    except FileNotFoundError:
        return Result(127, "", f"{argv[0]}: not found")
    except subprocess.TimeoutExpired:
        return Result(124, "", f"{argv[0]}: timed out after {timeout} s")
    except OSError as e:
        return Result(126, "", f"{argv[0]}: {e.strerror}")
