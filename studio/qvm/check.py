# Holds our own QVM reader and writer to the game's own scripts.
#
#   python -m studio check              both directions over the whole corpus
#   python -m studio check --read       only reading (qvm to qsc)
#   python -m studio check --write      only writing (qsc to qvm)
#   python -m studio check --show 5     print the first 5 differences in full
#
# Reading passes when our decompilation equals the ToolKit's, byte for byte.
# Writing passes when compiling that decompilation gives back the game's own
# file, byte for byte. Anything less and the ToolKit cannot be retired.
# The corpus comes from studio/qvm/corpus.py.
import pathlib, sys

from studio.qvm import read as R
from studio.qvm import write as W

ROOT = pathlib.Path(__file__).resolve().parents[2]


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def pairs(corpus):
    """(name, qvm path, qsc path) for everything captured."""
    out = []
    for q in sorted((corpus / "qvm").rglob("*.qvm")):
        rel = q.relative_to(corpus / "qvm")
        s = corpus / "qsc" / rel.with_suffix(".qsc")
        if s.exists():
            out.append((str(rel).replace("\\", "/"), q, s))
    return out


def main():
    corpus = pathlib.Path(arg("--corpus") or (ROOT / "corpus"))
    if not (corpus / "qvm").is_dir():
        raise SystemExit("no corpus at %s: run studio/qvm/corpus.py first" % corpus)
    show, shown = int(arg("--show") or 3), 0
    do_read = "--write" not in sys.argv
    do_write = "--read" not in sys.argv
    items = pairs(corpus)
    print("%d scripts in %s\n" % (len(items), corpus))

    read_ok = read_bad = write_ok = write_bad = 0
    for name, qvm_path, qsc_path in items:
        want_text = qsc_path.read_text(encoding="latin-1")
        want_bytes = qvm_path.read_bytes()

        if do_read:
            try:
                got = R.decompile(R.parse(qvm_path))
                if got == want_text:
                    read_ok += 1
                else:
                    read_bad += 1
                    if shown < show:
                        shown += 1
                        print("read  %s: text differs" % name)
                        for i, (a, b) in enumerate(zip(want_text.splitlines(), got.splitlines())):
                            if a != b:
                                print("   line %d\n     theirs %s\n     ours   %s" % (i + 1, a[:100], b[:100]))
                                break
            except Exception as e:
                read_bad += 1
                if shown < show:
                    shown += 1
                    print("read  %s: %s: %s" % (name, type(e).__name__, str(e)[:100]))

        if do_write:
            try:
                got = W.compile_text(want_text)
                if got == want_bytes:
                    write_ok += 1
                else:
                    write_bad += 1
                    if shown < show:
                        shown += 1
                        n = next((i for i in range(min(len(got), len(want_bytes)))
                                  if got[i] != want_bytes[i]), min(len(got), len(want_bytes)))
                        print("write %s: %d bytes, theirs %d, first difference at %d"
                              % (name, len(got), len(want_bytes), n))
            except Exception as e:
                write_bad += 1
                if shown < show:
                    shown += 1
                    print("write %s: %s: %s" % (name, type(e).__name__, str(e)[:100]))

    if do_read:
        print("\nread   %d of %d identical" % (read_ok, read_ok + read_bad))
    if do_write:
        print("write  %d of %d identical" % (write_ok, write_ok + write_bad))
    return 1 if (read_bad or write_bad) else 0


if __name__ == "__main__":
    sys.exit(main())
