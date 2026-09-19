# Reads IGI 1 script source (.qsc) into a syntax tree.
#
#   from qsc_parse import parse
#   tree = parse(open("objects.qsc").read())
#
# The language is small: expression statements, if/else, while, calls, the
# usual operators, and four kinds of literal. Names may carry dots
# (CutScene_3103.nTick), which the game treats as one identifier.
#
# Ported in part from project-igi-editor (https://github.com/HeavenHM/project-igi-editor),
# Copyright (c) 2026 HeavenHM, MIT licensed. See THIRD-PARTY-NOTICES.md.
import re, sys

# lower binds tighter, as in the decompiler
PRIORITY = {"*": 3, "/": 3, "+": 2, "-": 2, "<<": 5, ">>": 5,
            "<": 6, "<=": 6, ">": 6, ">=": 6, "==": 7, "!=": 7,
            "&": 8, "^": 9, "|": 10, "&&": 11, "||": 12, "=": 14}
UNARY = ("-", "+", "~", "!")
KEYWORDS = ("if", "else", "while")

_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<float>[0-9]+\.[0-9]*(?:[eE][-+]?[0-9]+)?|\.[0-9]+(?:[eE][-+]?[0-9]+)?|[0-9]+[eE][-+]?[0-9]+)
  | (?P<hex>0[xX][0-9a-fA-F]+)
  | (?P<int>[0-9]+)
  | (?P<name>[A-Za-z_][A-Za-z_0-9.]*)
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<op><<|>>|<=|>=|==|!=|&&|\|\||[-+*/&|^<>=~!])
  | (?P<punct>[(){},;])
""", re.X | re.S)


class QSCError(Exception):
    pass


class Node(object):
    __slots__ = ("kind", "value", "kids", "line")

    def __init__(self, kind, value=None, kids=None, line=0):
        self.kind, self.value, self.kids, self.line = kind, value, kids or [], line

    def __repr__(self):
        return "%s(%r)%s" % (self.kind, self.value, self.kids if self.kids else "")


def _unescape(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            out.append("\n" if n == "n" else "\t" if n == "t" else n)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def tokenize(text):
    toks, pos, line, n = [], 0, 1, len(text)
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m:
            raise QSCError("line %d: cannot read %r" % (line, text[pos:pos + 20]))
        kind = m.lastgroup
        value = m.group()
        line += value.count("\n")
        pos = m.end()
        if kind in ("space", "comment"):
            continue
        if kind == "string":
            value = _unescape(value[1:-1])
        elif kind == "name" and value in KEYWORDS:
            kind = value
        toks.append((kind, value, line))
    toks.append(("end", "", line))
    return toks


class _Parser(object):
    def __init__(self, toks):
        self.toks, self.i = toks, 0

    def peek(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def take(self, value):
        kind, got, line = self.peek()
        if got != value and kind != value:
            raise QSCError("line %d: expected %r, found %r" % (line, value, got or kind))
        return self.next()

    def at(self, value):
        kind, got, _ = self.peek()
        return got == value or kind == value

    # ---------------------------------------------------------------- statements
    def program(self):
        out = []
        while not self.at("end"):
            st = self.statement()
            if st is not None:
                out.append(st)
        return Node("block", kids=out)

    def statement(self):
        kind, value, line = self.peek()
        if value == ";":
            self.next()
            return None
        if value == "{":
            return self.block()
        if kind == "if":
            return self.if_stmt()
        if kind == "while":
            self.next()
            self.take("(")
            test = self.expression()
            self.take(")")
            return Node("while", kids=[test, self.body()], line=line)
        expr = self.expression()
        if self.at(";"):
            self.next()
        return Node("expr", kids=[expr], line=line)

    def block(self):
        self.take("{")
        out = []
        while not self.at("}"):
            if self.at("end"):
                raise QSCError("a block was never closed")
            st = self.statement()
            if st is not None:
                out.append(st)
        self.take("}")
        return Node("block", kids=out)

    def body(self):
        """A statement or a braced block, always returned as a block."""
        if self.at("{"):
            return self.block()
        st = self.statement()
        return Node("block", kids=[st] if st is not None else [])

    def if_stmt(self):
        _, _, line = self.next()
        self.take("(")
        test = self.expression()
        self.take(")")
        kids = [test, self.body()]
        if self.peek()[0] == "else":
            self.next()
            kids.append(self.if_stmt_as_block() if self.peek()[0] == "if" else self.body())
        return Node("if", kids=kids, line=line)

    def if_stmt_as_block(self):
        return Node("block", kids=[self.if_stmt()])

    # ---------------------------------------------------------------- expressions
    def expression(self, limit=99):
        left = self.unary()
        while True:
            kind, value, line = self.peek()
            if kind != "op" or value not in PRIORITY:
                break
            prio = PRIORITY[value]
            if prio > limit:
                break
            self.next()
            # "=" is right associative, the rest bind left to right: a && b && c
            # is (a && b) && c, which the game's compiler encodes in that order
            right = self.expression(prio if value == "=" else prio - 1)
            left = Node("binary", value, [left, right], line)
        return left

    def unary(self):
        kind, value, line = self.peek()
        if kind == "op" and value in UNARY:
            self.next()
            return Node("unary", value, [self.unary()], line)
        return self.postfix()

    def postfix(self):
        node = self.primary()
        while self.at("("):
            if node.kind != "ident":
                raise QSCError("line %d: only a name can be called" % node.line)
            self.next()
            args = []
            if not self.at(")"):
                while True:
                    args.append(self.expression())
                    if self.at(","):
                        self.next()
                        continue
                    break
            self.take(")")
            node = Node("call", node.value, args, node.line)
        return node

    def primary(self):
        kind, value, line = self.next()
        if kind == "int":
            return Node("int", int(value), line=line)
        if kind == "hex":
            return Node("int", int(value, 16), line=line)
        if kind == "float":
            return Node("float", float(value), line=line)
        if kind == "string":
            return Node("string", value, line=line)
        if kind == "name":
            return Node("ident", value, line=line)
        if value == "(":
            inner = self.expression()
            self.take(")")
            return inner
        raise QSCError("line %d: unexpected %r" % (line, value or kind))


def parse(text):
    """Source to a tree. Raises QSCError with a line number on bad input."""
    return _Parser(tokenize(text)).program()


def main(argv):
    if not argv:
        print("usage: qsc_parse.py <file.qsc>")
        return 2
    tree = parse(open(argv[0], encoding="latin-1").read())
    print("%d top level statements" % len(tree.kids))
    for st in tree.kids[:10]:
        print("  " + repr(st)[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
