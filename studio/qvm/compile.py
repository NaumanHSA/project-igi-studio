# Compiles IGI 1 .qsc scripts to .qvm and installs them into a mission slot.
#
#   from studio.qvm.compile import compile_qsc, decompile_qvm
#   (installing a built mission into a slot is studio/build/install.py)
#
# The compiling and decompiling is ours (studio/qvm/write.py, studio/qvm/read.py):
# no third party tool is involved and nothing has to be installed. Both are held
# to the game's own scripts, which they reproduce byte for byte, all 884 of them
# (studio/qvm/corpus.py captures them, studio/qvm/check.py checks them).
import pathlib, sys

from studio import protect
from studio.qvm import read as QR
from studio.qvm import write as QW
from studio.qvm.qsc import QSCError
from studio import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUTDIR = paths.cache() / "compiled"        # where a compiled script is staged


class CompileError(RuntimeError):
    pass


def available():
    """Kept for callers that used to ask whether the ToolKit was installed."""
    return True


def compile_qsc(src):
    """Compile one .qsc and return the path of the resulting .qvm."""
    src = pathlib.Path(src)
    if not src.exists():
        raise CompileError("source not found: %s" % src)
    try:
        data = QW.compile_text(src.read_text(encoding="latin-1"))
    except (QSCError, QR.QVMError) as e:
        raise CompileError("%s: %s" % (src.name, e))
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / (src.stem + ".qvm")
    out.write_bytes(data)
    return out


def decompile_qvm(src, outdir):
    """Decompile a .qvm back to .qsc, for reading a level out of the game."""
    src, outdir = pathlib.Path(src), pathlib.Path(outdir)
    if not src.exists():
        raise CompileError("file not found: %s" % src)
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        text = QR.decompile(QR.parse(src))
    except QR.QVMError as e:
        raise CompileError("%s: %s" % (src.name, e))
    out = outdir / (src.stem + ".qsc")
    # CRLF, as the game's own tools wrote these files, so a decompilation made
    # here is byte for byte what one made there was
    out.write_text(text, encoding="latin-1", newline="\r\n")
    return out


def decompile_dir(src_dir, outdir):
    """Decompile every .qvm in a folder (a slot's AI scripts)."""
    src_dir, outdir = pathlib.Path(src_dir), pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for f in outdir.glob("*.qsc"):
        f.unlink()
    n = 0
    for f in sorted(src_dir.glob("*.qvm")):
        decompile_qvm(f, outdir)
        n += 1
    return n
