# The IGI ToolKit's compiler and decompiler, kept only to capture the corpus
# our own compiler is tested against (studio/qvm/corpus.py, studio/qvm/check.py).
#
# Nothing in the studio builds with this any more: studio/qvm/write.py and
# studio/qvm/read.py do that, and they match this tool byte for byte on all 884
# scripts the game ships. This module is here so the corpus can be rebuilt on a
# machine that has the ToolKit installed.
#
#   import toolkit_qsc
#
# Pipeline, same as the ToolKit's own batch files:
#   objects.qsc --gconv--> QVM v7 (IGI 2 format) --dconv convert--> QVM v5 (IGI 1)
#
# dconv writes its converted output still carrying a .qsc extension; renaming it
# is not cosmetic, miss it and you get nothing.
import os, pathlib, shutil, subprocess

from studio import protect

QROOT = pathlib.Path(os.path.expandvars(r"%APPDATA%\QEditor\QCompiler"))
GCONV = QROOT / "Tools" / "GConv"
DCONV = QROOT / "Tools" / "DConv"
OUTDIR = QROOT / "Compile" / "output"

CREATE_NO_WINDOW = 0x08000000


class CompileError(RuntimeError):
    pass


def _clean(*dirs):
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        for f in d.iterdir():
            if f.is_file():
                f.unlink()
            else:
                shutil.rmtree(f, ignore_errors=True)


def available():
    return (GCONV / "gconv.exe").exists() and (DCONV / "dconv.exe").exists()


def compile_qsc(src):
    """Compile one .qsc and return the path of the resulting .qvm."""
    src = pathlib.Path(src)
    if not src.exists():
        raise CompileError("source not found: %s" % src)
    if not available():
        raise CompileError("gconv/dconv not found under %s - is the IGI ToolKit installed?" % QROOT)
    name = src.stem
    _clean(QROOT / "Compile" / "input", OUTDIR, GCONV / "input",
           GCONV / "output", DCONV / "input", DCONV / "output")

    shutil.copyfile(src, GCONV / "input" / (name + ".qsc"))
    r = subprocess.run([str(GCONV / "gconv.exe"), "compile_scripts.qsc"], cwd=str(GCONV),
                       capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    built = GCONV / "input" / (name + ".qvm")
    if r.returncode != 0 or not built.exists():
        raise CompileError("gconv failed on %s\n%s%s" % (src.name, r.stdout[-800:], r.stderr[-800:]))

    shutil.move(str(built), str(DCONV / "output" / (name + ".qvm")))
    r = subprocess.run([str(DCONV / "dconv.exe"), "qvm", "convert", "output", str(OUTDIR)],
                       cwd=str(DCONV), capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise CompileError("dconv convert failed\n%s%s" % (r.stdout[-800:], r.stderr[-800:]))

    for f in OUTDIR.glob("*.qsc"):
        f.rename(f.with_suffix(".qvm"))
    out = OUTDIR / (name + ".qvm")
    if not out.exists():
        raise CompileError("conversion produced no output for %s" % src.name)
    return out


def decompile_qvm(src, outdir):
    """Decompile a .qvm back to .qsc, for reading a custom slot out of the game."""
    src, outdir = pathlib.Path(src), pathlib.Path(outdir)
    if not (DCONV / "dconv.exe").exists():
        raise CompileError("dconv not found under %s" % DCONV)
    outdir.mkdir(parents=True, exist_ok=True)
    _clean(DCONV / "input", DCONV / "output")
    shutil.copyfile(src, DCONV / "input" / src.name)
    r = subprocess.run([str(DCONV / "dconv.exe"), "qvm", "decompile", "input", str(outdir)],
                       cwd=str(DCONV), capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
    out = outdir / (src.stem + ".qsc")
    if r.returncode != 0 or not out.exists():
        raise CompileError("dconv decompile failed\n%s%s" % (r.stdout[-800:], r.stderr[-800:]))
    return out


def decompile_dir(src_dir, outdir):
    """Decompile every .qvm in a folder (a slot's AI scripts) in one dconv run."""
    src_dir, outdir = pathlib.Path(src_dir).resolve(), pathlib.Path(outdir).resolve()
    if not (DCONV / "dconv.exe").exists():
        raise CompileError("dconv not found under %s" % DCONV)
    outdir.mkdir(parents=True, exist_ok=True)
    for f in outdir.glob("*.qsc"):
        f.unlink()
    _clean(DCONV / "input", DCONV / "output")
    files = list(src_dir.glob("*.qvm"))
    for f in files:
        shutil.copyfile(f, DCONV / "input" / f.name)
    if not files:
        return 0
    r = subprocess.run([str(DCONV / "dconv.exe"), "qvm", "decompile", "input", str(outdir)],
                       cwd=str(DCONV), capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise CompileError("dconv decompile failed\n%s%s" % (r.stdout[-800:], r.stderr[-800:]))
    return len(list(outdir.glob("*.qsc")))


