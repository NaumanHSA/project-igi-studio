# The entry point of the bundled server (studio-server.exe, built by PyInstaller).
#
# It stands in for "python" wherever the studio calls itself:
#
#   studio-server.exe serve --port 0 --token-stdin     the studio's own commands
#   studio-server.exe -m studio.build.plan ...         run one module, as python -m
#
# The studio starts its builder and its data extractors as separate processes
# with [sys.executable, "-m", module]. Bundled, sys.executable is this program,
# so "-m" has to mean here what it means to Python.
import multiprocessing
import runpy
import sys


def main():
    # the terrain extractor works in parallel; a bundled program has to let
    # multiprocessing take over its worker processes before anything else
    multiprocessing.freeze_support()
    if len(sys.argv) > 2 and sys.argv[1] == "-m":
        module = sys.argv[2]
        sys.argv = [module] + sys.argv[3:]
        runpy.run_module(module, run_name="__main__", alter_sys=True)
        return 0
    from studio.__main__ import main as studio
    return studio(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main() or 0)
