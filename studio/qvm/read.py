# Reads IGI 1 script bytecode (.qvm) without any third party tool.
#
#   from qvm_read import parse, disasm
#   q = parse("objects.qvm");  print(q.header, len(q.code))
#   python studio/qvm/read.py <file.qvm> [--disasm]
#
# The format is "LOOP 8.5": a 60 byte header, a table of identifiers (function
# and constant names), a table of string literals, and the code, which is a
# stack machine with 49 one byte opcodes and little endian operands.
#
# Ported from project-igi-editor (https://github.com/HeavenHM/project-igi-editor),
# Copyright (c) 2026 HeavenHM, MIT licensed, and its written description of the
# format. See THIRD-PARTY-NOTICES.md.
import struct, sys

MAGIC = b"LOOP"
VERSION = (8, 5)

OPS = [
    "BRK", "NOP", "PUSH", "PUSHB", "PUSHW", "PUSHF", "PUSHA", "PUSHS",
    "PUSHSI", "PUSHSIB", "PUSHSIW", "PUSHI", "PUSHII", "PUSHIIB", "PUSHIIW",
    "PUSH0", "PUSH1", "PUSHM", "POP", "RET",
    "BRA", "BF", "BT", "JSR", "CALL",
    "ADD", "SUB", "MUL", "DIV", "SHL", "SHR", "AND", "OR", "XOR",
    "LAND", "LOR", "EQ", "NE", "LT", "LE", "GT", "GE",
    "ASSIGN", "PLUS", "MINUS", "INV", "NOT",
    "BLK", "ILLEGAL",
]
OP = {name: i for i, name in enumerate(OPS)}

# bytes of operand after the opcode; CALL is a count followed by that many ints
OPERAND = {
    "PUSH": 4, "PUSHB": 1, "PUSHW": 2, "PUSHF": 4, "PUSHA": 4, "PUSHS": 4,
    "PUSHSI": 4, "PUSHSIB": 1, "PUSHSIW": 2,
    "PUSHI": 4, "PUSHII": 4, "PUSHIIB": 1, "PUSHIIW": 2,
    "BRA": 4, "BF": 4, "BT": 4, "JSR": 4,
    "CALL": -1,
}
HEADER_FIELDS = ("of_itable", "of_ivalue", "sz_itable", "sz_ivalue",
                 "of_stable", "of_svalue", "sz_stable", "sz_svalue",
                 "of_ctable", "sz_ctable", "unknown_1", "unknown_2")


class QVMError(Exception):
    pass


class Instr(object):
    __slots__ = ("op", "operand", "fvalue", "targets", "address", "size")

    def __init__(self, op, address):
        self.op, self.address = op, address
        self.operand, self.fvalue, self.targets, self.size = 0, 0.0, None, 1

    def __repr__(self):
        if self.op == "CALL":
            return "CALL %s" % (self.targets,)
        if self.op == "PUSHF":
            return "PUSHF %g" % self.fvalue
        return "%s %d" % (self.op, self.operand) if self.op in OPERAND else self.op


class QVM(object):
    def __init__(self):
        self.header = {}
        self.identifiers = []       # itable: names of functions and constants
        self.strings = []           # stable: string literals
        self.code = []              # list of Instr
        self.tail = b""             # anything after the code section

    def ident(self, i):
        return self.identifiers[i] if 0 <= i < len(self.identifiers) else "id%d" % i

    def string(self, i):
        return self.strings[i] if 0 <= i < len(self.strings) else ""


def _split_strings(blob):
    """The pools are null terminated strings packed together; keep the order."""
    out, start = [], 0
    for i, b in enumerate(blob):
        if b == 0:
            out.append(blob[start:i].decode("latin-1"))
            start = i + 1
    if start < len(blob):
        out.append(blob[start:].decode("latin-1"))
    return out


def parse(src):
    """Parse bytes or a path into a QVM. Raises QVMError on anything unexpected."""
    data = src if isinstance(src, (bytes, bytearray)) else open(str(src), "rb").read()
    data = bytes(data)
    if len(data) < 60:
        raise QVMError("file is %d bytes, too small for a 60 byte header" % len(data))
    if data[:4] != MAGIC:
        raise QVMError("not a QVM: magic is %r, expected %r" % (data[:4], MAGIC))
    q = QVM()
    nums = struct.unpack_from("<14I", data, 4)
    if (nums[0], nums[1]) != VERSION:
        raise QVMError("unsupported QVM version %d.%d, expected 8.5" % (nums[0], nums[1]))
    q.header = {"ver_major": nums[0], "ver_minor": nums[1]}
    q.header.update(dict(zip(HEADER_FIELDS, nums[2:])))
    h = q.header

    for off, size, name in ((h["of_ivalue"], h["sz_ivalue"], "identifiers"),
                            (h["of_svalue"], h["sz_svalue"], "strings")):
        if size:
            if off + size > len(data):
                raise QVMError("%s run past the end of the file" % name)
            setattr(q, name, _split_strings(data[off:off + size]))

    off, size = h["of_ctable"], h["sz_ctable"]
    if size:
        if off + size > len(data):
            raise QVMError("code runs past the end of the file")
        q.code = _decode(data[off:off + size])
        end = off + size
        q.tail = data[end:]
    return q


def _decode(code):
    out, pos, n = [], 0, len(code)
    while pos < n:
        b = code[pos]
        if b >= len(OPS):
            raise QVMError("unknown opcode 0x%02x at %d" % (b, pos))
        ins = Instr(OPS[b], pos)
        pos += 1
        want = OPERAND.get(ins.op, 0)
        if want == -1:                                  # CALL: count, then targets
            if pos + 4 > n:
                raise QVMError("CALL at %d has no argument count" % ins.address)
            count = struct.unpack_from("<I", code, pos)[0]
            pos += 4
            if pos + count * 4 > n:
                raise QVMError("CALL at %d wants %d arguments, past the end" % (ins.address, count))
            ins.operand = count
            ins.targets = list(struct.unpack_from("<%di" % count, code, pos)) if count else []
            pos += count * 4
            ins.size = 5 + count * 4
        elif want:
            if pos + want > n:
                raise QVMError("%s at %d has a short operand" % (ins.op, ins.address))
            if want == 4:
                ins.operand = struct.unpack_from("<I", code, pos)[0]
                if ins.op == "PUSHF":
                    ins.fvalue = struct.unpack_from("<f", code, pos)[0]
            elif want == 2:
                ins.operand = struct.unpack_from("<H", code, pos)[0]
            else:
                ins.operand = code[pos]
            pos += want
            ins.size = 1 + want
        out.append(ins)
    return out


# ---------------------------------------------------------------- back to QSC
#
# The code is a stack machine, so reading it back is a matter of replaying it
# with an expression stack instead of values. Calls carry the address of each
# argument's code, and each argument ends with BRK, which is what makes this
# possible at all. A BF whose target is preceded by a BRA is an if with an else
# when that BRA jumps forward, and a while when it jumps back.

PRIORITY = {"+": 2, "-": 2, "*": 3, "/": 3, "<<": 5, ">>": 5, "&": 8, "|": 10,
            "^": 9, "&&": 11, "||": 12, "==": 7, "!=": 7, "<": 6, "<=": 6,
            ">": 6, ">=": 6, "=": 14, "~": 2, "!": 2}
UNARY = {"PLUS": "+", "MINUS": "-", "INV": "~", "NOT": "!"}
BINARY = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "SHL": "<<", "SHR": ">>",
          "AND": "&", "OR": "|", "XOR": "^", "LAND": "&&", "LOR": "||",
          "EQ": "==", "NE": "!=", "LT": "<", "LE": "<=", "GT": ">", "GE": ">=",
          "ASSIGN": "="}


def _s32(v):
    return v - 0x100000000 if v >= 0x80000000 else v


def fstr(v):
    """A float as the game's own tools write it.

    They print the shortest decimal that reads back as the same number, which
    is what Python's repr gives: a 32 bit -0.4 comes out -0.4000000059604645,
    not the 17 digit -0.40000000596046448 that %.17g would print."""
    s = repr(float(v))
    if "e" not in s and "E" not in s and "." not in s:
        s += ".0"
    return s


def _esc(s):
    return s.replace("\n", "\\n").replace('"', '\\"')


class Node(object):
    __slots__ = ("kind", "value", "op", "a", "b", "callee", "args", "test", "body", "other")

    def __init__(self, kind, **kw):
        self.kind = kind
        for k in self.__slots__[1:]:
            setattr(self, k, kw.get(k))

    def text(self, tabs=0):
        k = self.kind
        if k in ("num", "const", "str", "ident"):
            return self.value
        if k == "paren":
            return "(" + self.a.text(tabs) + ")"
        if k == "unary":
            return self.op + self.a.text(tabs)
        if k == "binary":
            return self.a.text(tabs) + " " + self.op + " " + self.b.text(tabs)
        if k == "call":
            return self._call_text(tabs)
        if k == "while":
            return self._block("while(" + self.test.text(tabs + 1) + ")", self.body, tabs, "\n")
        if k == "if":
            out = self._block("if(" + self.test.text(tabs + 1) + ")", self.body, tabs, "")
            if self.other is not None:
                out += self._block("else", self.other, tabs, "\n")
            return out
        raise QVMError("cannot write node %s" % k)

    def _call_text(self, tabs):
        head = self.callee.text(tabs)
        width, parts = len(head), []
        for arg in self.args:
            if not arg:
                continue
            s = arg[0].text(tabs + 1)
            if arg[0].kind == "call":
                s = "\n" + "\t" * (tabs + 1) + s
                width = len(s) + 2
            elif width + len(s) > 300:
                s = "\n" + s
                width = len(s) + 2
            else:
                width += len(s) + 2
            parts.append(s)
        return head + "(" + ", ".join(parts) + ")"

    def _block(self, head, body, tabs, nested_gap):
        """nested_gap is the blank line a nested block gets here: an else and a
        while body leave one after it, the true half of an if does not."""
        t = "\t" * tabs
        out = t + head + "\n" + t + "{\n"
        for st in body or []:
            if st.kind in ("if", "while"):
                out += st.text(tabs + 1) + nested_gap
            else:
                out += "\t" * (tabs + 1) + st.text(tabs + 1) + ";\n"
        return out + t + "}\n"


def _walk(q, at, address, until=None):
    """Replay the code from one address, returning (statements, next address)."""
    out = []
    while True:
        i = at.get(address)
        if i is None:
            break
        ins = q.code[i]
        if until is not None and ins.address == until:
            break
        op = ins.op
        if op in ("BRK", "BRA", "RET"):
            break
        after = ins.address + ins.size

        if op in ("NOP", "POP"):
            address = after
        elif op in ("PUSH", "PUSHB", "PUSHW", "PUSHF"):
            out.append(Node("num", value=fstr(ins.fvalue) if op == "PUSHF" else str(ins.operand)))
            address = after
        elif op in ("PUSH0", "PUSH1", "PUSHM"):
            out.append(Node("const", value={"PUSH0": "0", "PUSH1": "1", "PUSHM": "4294967295"}[op]))
            address = after
        elif op in ("PUSHSI", "PUSHSIB", "PUSHSIW"):
            out.append(Node("str", value='"%s"' % _esc(q.string(ins.operand))))
            address = after
        elif op in ("PUSHII", "PUSHIIB", "PUSHIIW"):
            out.append(Node("ident", value=_esc(q.ident(ins.operand))))
            address = after
        elif op in UNARY:
            if not out:
                raise QVMError("%s at %d has nothing to apply to" % (op, ins.address))
            a = out.pop()
            if a.kind in ("unary", "binary"):
                a = Node("paren", a=a)
            out.append(Node("unary", op=UNARY[op], a=a))
            address = after
        elif op in BINARY:
            if len(out) < 2:
                raise QVMError("%s at %d wants two operands" % (op, ins.address))
            sym = BINARY[op]
            b, a = out.pop(), out.pop()
            if b.kind == "binary" and PRIORITY[sym] < PRIORITY[b.op]:
                b = Node("paren", a=b)
            if a.kind == "binary" and PRIORITY[sym] < PRIORITY[a.op]:
                a = Node("paren", a=a)
            out.append(Node("binary", op=sym, a=a, b=b))
            address = after
        elif op == "CALL":
            if not out:
                raise QVMError("CALL at %d has no callee" % ins.address)
            callee, args = out.pop(), []
            for target in ins.targets or []:
                got, _ = _walk(q, at, target & 0xFFFFFFFF)
                args.append(got)
            out.append(Node("call", callee=callee, args=args))
            # the BRA after a call jumps over the argument code
            j = at.get(after)
            if j is None:
                address = after
            else:
                ex = q.code[j]
                address = ex.address + ex.size + _s32(ex.operand)
        elif op == "BF":
            if not out:
                raise QVMError("BF at %d has no test" % ins.address)
            test = out.pop()
            target = after + _s32(ins.operand)
            ex = q.code[at[target - 5]] if (target >= 5 and (target - 5) in at) else None
            jump = _s32(ex.operand) if (ex is not None and ex.op == "BRA") else 0
            if jump < 0:                                    # jumps back: a loop
                body, _ = _walk(q, at, after)
                out.append(Node("while", test=test, body=body))
                address = target
            else:
                body, _ = _walk(q, at, after)
                if jump > 0:                                # jumps on: an else
                    stop = ex.address + ex.size + jump
                    other, _ = _walk(q, at, target, stop)
                    out.append(Node("if", test=test, body=body, other=other))
                    address = stop
                else:
                    out.append(Node("if", test=test, body=body))
                    address = target
        else:
            raise QVMError("cannot read %s at %d" % (op, ins.address))
    return out, address


def decompile(q):
    """The script as QSC source, in the layout the game's own tools produce."""
    if not q.code:
        return ""
    at = {ins.address: i for i, ins in enumerate(q.code)}
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 20000))
    try:
        tree, _ = _walk(q, at, 0)
    finally:
        sys.setrecursionlimit(old)
    out = []
    for st in tree:
        out.append(st.text(0) if st.kind in ("if", "while") else st.text(0) + ";\n")
    return "".join(out)


def disasm(q):
    """The code as text, one instruction a line, with names resolved."""
    lines = []
    for ins in q.code:
        a = "%6d  %-8s" % (ins.address, ins.op)
        if ins.op == "CALL":
            a += "%d args" % ins.operand
        elif ins.op == "PUSHF":
            a += "%g" % ins.fvalue
        elif ins.op in ("PUSHI", "PUSHII", "PUSHIIB", "PUSHIIW"):
            a += "%d  ; %s" % (ins.operand, q.ident(ins.operand))
        elif ins.op in ("PUSHS", "PUSHSI", "PUSHSIB", "PUSHSIW"):
            a += '%d  ; "%s"' % (ins.operand, q.string(ins.operand))
        elif ins.op in OPERAND:
            a += "%d" % ins.operand
        lines.append(a.rstrip())
    return "\n".join(lines)


def main(argv):
    if not argv:
        print(__doc__ or "usage: qvm_read.py <file.qvm> [--disasm]")
        return 2
    q = parse(argv[0])
    print("version %d.%d, %d identifiers, %d strings, %d instructions, %d tail bytes"
          % (q.header["ver_major"], q.header["ver_minor"], len(q.identifiers),
             len(q.strings), len(q.code), len(q.tail)))
    if "--disasm" in argv:
        print(disasm(q))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
