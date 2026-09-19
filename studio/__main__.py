"""One way in to everything the studio can do from a terminal.

  python -m studio setup              find the game and get ready
  python -m studio                    start the server and open the editor
  python -m studio serve --port 8765  the same, on a port of your choosing
  python -m studio build --plan p.json --out missions/plan --game <game>
  python -m studio corpus             capture the game's scripts (needs the ToolKit)
  python -m studio check              our compiler against that corpus
  python -m studio extract levels     rebuild the editor's data from the game

Anything after the command is passed to it unchanged.
"""
import runpy, sys

COMMANDS = {
    "setup": "studio.setup",
    "serve": "studio.server.app",
    "build": "studio.build.plan",
    "install": "studio.build.migrate",
    "corpus": "studio.qvm.corpus",
    "check": "studio.qvm.check",
    "read": "studio.qvm.read",
    "write": "studio.qvm.write",
}
EXTRACT = {
    "levels": "studio.extract.levels",
    "models": "studio.extract.models",
    "ground": "studio.extract.ground",
    "meshes": "studio.extract.meshes",
    "catalog": "studio.extract.catalog",
    "library": "studio.extract.library",
    "terrain": "studio.extract.terrain",
    "graphs": "studio.extract.graphs",
}


def usage(bad=None):
    if bad:
        print("unknown command: %s\n" % bad)
    print(__doc__.strip())
    print("\ncommands: %s" % ", ".join(sorted(COMMANDS)))
    print("extract:  %s" % ", ".join(sorted(EXTRACT)))
    return 2


def main(argv):
    if not argv:
        argv = ["serve"]
    cmd, rest = argv[0], argv[1:]
    if cmd in ("-h", "--help", "help"):
        return usage()
    if cmd == "extract":
        if not rest or rest[0] not in EXTRACT:
            return usage(rest[0] if rest else "extract what?")
        target, rest = EXTRACT[rest[0]], rest[1:]
    elif cmd in COMMANDS:
        target = COMMANDS[cmd]
    else:
        return usage(cmd)
    sys.argv = [target.replace(".", "/") + ".py"] + rest
    runpy.run_module(target, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
