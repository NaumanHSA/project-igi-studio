# Compiles IGI 1 script source (.qsc) to bytecode (.qvm), with no third party
# tool in the way. This is what replaces gconv.exe and dconv.exe.
#
#   from qvm_write import compile_text, compile_file
#   data = compile_text(open("objects.qsc").read())
#   compile_file("objects.qsc", "objects.qvm")
#
# The output is held to a hard standard: for every script the game ships,
# compiling the decompilation must give back the original bytes. See
# studio/qvm/check.py and studio/qvm/corpus.py.
#
# Layout, as the game's own compiler lays it out:
#
#   header      60 bytes, "LOOP" 8.5, then the offsets and sizes below
#   itable      one 4 byte offset per identifier, into ivalue
#   ivalue      the identifier names, null terminated, in first use order
#   stable      one 4 byte offset per string literal, into svalue
#   svalue      the string literals, null terminated, in first use order
#   code        the instructions
#
# A call is: push the name, CALL with the argument count and the address of
# each argument's code, then a BRA over the argument block, then each argument
# followed by BRK. An expression statement ends with POP.
#
# Ported from project-igi-editor (https://github.com/HeavenHM/project-igi-editor),
# Copyright (c) 2026 HeavenHM, MIT licensed. See THIRD-PARTY-NOTICES.md.
import pathlib, struct, sys

from studio.qvm.qsc import parse, QSCError
from studio.qvm.read import OP, QVMError

BINARY = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "<<": "SHL", ">>": "SHR",
          "&": "AND", "|": "OR", "^": "XOR", "&&": "LAND", "||": "LOR",
          "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
          "=": "ASSIGN"}
UNARY = {"-": "MINUS", "+": "PLUS", "~": "INV", "!": "NOT"}


class Writer(object):
    def __init__(self):
        self.code = bytearray()
        self.idents, self.ident_at = [], {}
        self.strings, self.string_at = [], {}

    # ---------------------------------------------------------------- bytes
    def op(self, name):
        self.code.append(OP[name])

    def u8(self, v):
        self.code.append(v & 0xFF)

    def u16(self, v):
        self.code += struct.pack("<H", v & 0xFFFF)

    def u32(self, v):
        self.code += struct.pack("<I", v & 0xFFFFFFFF)

    def at32(self, where, v):
        self.code[where:where + 4] = struct.pack("<I", v & 0xFFFFFFFF)

    def here(self):
        return len(self.code)

    # ---------------------------------------------------------------- pools
    def intern(self, pool, index, value):
        i = index.get(value)
        if i is None:
            i = index[value] = len(pool)
            pool.append(value)
        return i

    def push_ident(self, name):
        i = self.intern(self.idents, self.ident_at, name)
        self._push_indexed(i, "PUSHIIB", "PUSHIIW", "PUSHII")

    def push_string(self, s):
        i = self.intern(self.strings, self.string_at, s)
        self._push_indexed(i, "PUSHSIB", "PUSHSIW", "PUSHSI")

    def _push_indexed(self, i, b, w, l):
        if i < 0x100:
            self.op(b), self.u8(i)
        elif i < 0x10000:
            self.op(w), self.u16(i)
        else:
            self.op(l), self.u32(i)

    def push_int(self, v):
        # The pools and these choices are what make the output byte for byte
        # what the game ships: 0 and 1 have their own opcodes, -1 is PUSHM,
        # and the smallest unsigned width wins. A negative literal never
        # reaches here: the reader writes it as a unary minus.
        if v == 0:
            return self.op("PUSH0")
        if v == 1:
            return self.op("PUSH1")
        if v in (-1, 0xFFFFFFFF):
            return self.op("PUSHM")
        # the narrow forms hold a signed value, so 242 needs PUSHW, not PUSHB
        # (the corpus shows PUSHB 2..127 and PUSHW 128..10000). Pool indices
        # are unsigned and go through _push_indexed instead.
        if -128 <= v <= 127:
            self.op("PUSHB"), self.u8(v)
        elif -32768 <= v <= 32767:
            self.op("PUSHW"), self.u16(v)
        else:
            self.op("PUSH"), self.u32(v)

    def push_float(self, v):
        # 0, 1 and -1 have their own opcodes even when the source wrote them as
        # floats, which is why no script the game ships ever pushes a float of
        # those values. The virtual machine does not mind: it keeps no types.
        if v == 0.0:
            return self.op("PUSH0")
        if v == 1.0:
            return self.op("PUSH1")
        if v == -1.0:
            return self.op("PUSHM")
        self.op("PUSHF")
        self.code += struct.pack("<f", v)

    # ---------------------------------------------------------------- tree
    def expr(self, n):
        k = n.kind
        if k == "int":
            self.push_int(n.value)
        elif k == "float":
            self.push_float(n.value)
        elif k == "string":
            self.push_string(n.value)
        elif k == "ident":
            self.push_ident(n.value)
        elif k == "unary":
            self.expr(n.kids[0])
            self.op(UNARY[n.value])
        elif k == "binary":
            self.expr(n.kids[0])
            self.expr(n.kids[1])
            self.op(BINARY[n.value])
        elif k == "call":
            self.call(n)
        else:
            raise QVMError("cannot compile expression %s" % k)

    def call(self, n):
        self.push_ident(n.value)
        self.op("CALL")
        self.u32(len(n.kids))
        slots = self.here()
        for _ in n.kids:
            self.u32(0)
        bra = self.here()
        self.op("BRA")
        bra_slot = self.here()
        self.u32(0)
        for i, arg in enumerate(n.kids):
            self.at32(slots + i * 4, self.here())
            self.expr(arg)
            self.op("BRK")
        self.at32(bra_slot, self.here() - (bra + 5))

    def stmt(self, n):
        k = n.kind
        if k == "block":
            for c in n.kids:
                self.stmt(c)
        elif k == "expr":
            self.expr(n.kids[0])
            self.op("POP")
        elif k == "if":
            self.if_stmt(n)
        elif k == "while":
            self.while_stmt(n)
        else:
            raise QVMError("cannot compile statement %s" % k)

    def if_stmt(self, n):
        self.expr(n.kids[0])
        self.op("BF")
        bf_slot = self.here()
        self.u32(0)
        self.stmt(n.kids[1])
        # A BRA always follows the true half: with an else it jumps over it,
        # without one it jumps nowhere. The reader needs it either way to know
        # where the block ends, and the game's compiler emits it too.
        self.op("BRA")
        bra_slot = self.here()
        self.u32(0)
        bra_end = self.here()
        self.at32(bf_slot, bra_end - (bf_slot + 4))
        if len(n.kids) > 2:
            self.stmt(n.kids[2])
        self.at32(bra_slot, self.here() - bra_end)

    def while_stmt(self, n):
        top = self.here()
        self.expr(n.kids[0])
        self.op("BF")
        bf_slot = self.here()
        self.u32(0)
        self.stmt(n.kids[1])
        self.op("BRA")
        bra_slot = self.here()
        self.u32(0)
        end = self.here()
        self.at32(bra_slot, top - end)          # back to the test
        self.at32(bf_slot, end - (bf_slot + 4))  # out of the loop

    # ---------------------------------------------------------------- file
    def bytes_out(self):
        def pool(values):
            table, blob = bytearray(), bytearray()
            for v in values:
                table += struct.pack("<I", len(blob))
                blob += v.encode("latin-1") + b"\0"
            return bytes(table), bytes(blob)

        itable, ivalue = pool(self.idents)
        stable, svalue = pool(self.strings)
        of_itable = 60
        of_ivalue = of_itable + len(itable)
        of_stable = of_ivalue + len(ivalue)
        of_svalue = of_stable + len(stable)
        of_ctable = of_svalue + len(svalue)
        head = struct.pack("<4s14I", b"LOOP", 8, 5,
                           of_itable, of_ivalue, len(itable), len(ivalue),
                           of_stable, of_svalue, len(stable), len(svalue),
                           of_ctable, len(self.code), 0, 0)
        return head + itable + ivalue + stable + svalue + bytes(self.code)


def compile_tree(tree):
    w = Writer()
    w.stmt(tree)
    w.op("BRK")          # the code ends with a terminator, as the game's does
    return w.bytes_out()


def compile_text(text):
    """QSC source to QVM bytes."""
    return compile_tree(parse(text))


def compile_file(src, dst=None):
    src = pathlib.Path(src)
    data = compile_text(src.read_text(encoding="latin-1"))
    dst = pathlib.Path(dst) if dst else src.with_suffix(".qvm")
    dst.write_bytes(data)
    return dst


def main(argv):
    if not argv:
        print("usage: qvm_write.py <file.qsc> [out.qvm]")
        return 2
    out = compile_file(argv[0], argv[1] if len(argv) > 1 else None)
    print("%s  %d bytes" % (out, out.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
