# The QVM script format

Every mission in *Project I.G.I.: I'm Going In* is a compiled script. Guards,
objectives, triggers, cutscenes and the mission list itself are all `.qvm`
files, and until now the only way to read or write one was the IGI ToolKit's
`gconv.exe` and `dconv.exe`. The studio does it itself, in
[`studio/qvm`](../studio/qvm), with nothing installed.

This is the format as that code implements it, and how the implementation is
held to the game's own files.

**Credit.** The format was worked out by HeavenHM in
[project-igi-editor](https://github.com/HeavenHM/project-igi-editor): C++
parsers, and a written description of the header, the string tables and the
opcode table. Our reader, writer and QSC parser are ported from that work, and
each file names it in its header. See [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md).
What this page adds is what byte-exactness turned out to require, which is most
of the detail below.

## The file

Six sections, in this order, no padding between them.

| Section | What is in it |
|---|---|
| header | 60 bytes: `LOOP`, version 8.5, then the offset and size of everything else |
| itable | one uint32 per identifier, its offset into `ivalue` |
| ivalue | the identifier names, null terminated, in first use order |
| stable | one uint32 per string literal, its offset into `svalue` |
| svalue | the string literals, null terminated, in first use order |
| code | the instructions |

Identifiers are the names of functions and constants (`Task_HumanSoldier`,
`CutScene_3103.nTick`). String literals are the quoted text. They live in
separate pools and are pushed by separate opcodes.

## Header

`LOOP`, then fourteen little endian uint32.

| Word | Field | Note |
|---|---|---|
| 1, 2 | version major, minor | Always 8 and 5. Anything else is rejected |
| 3, 4 | `of_itable`, `of_ivalue` | Where the identifier table and its text start |
| 5, 6 | `sz_itable`, `sz_ivalue` | Their sizes in bytes |
| 7, 8 | `of_stable`, `of_svalue` | The same for string literals |
| 9, 10 | `sz_stable`, `sz_svalue` | |
| 11, 12 | `of_ctable`, `sz_ctable` | Where the code starts, and how long it is |
| 13, 14 | unknown | Zero in every script the game ships; written as zero |

Anything after the code section is kept as a tail and not interpreted. No
shipped script has one.

## Instructions

One byte of opcode, then a little endian operand of a fixed width. 49 opcodes:

| # | Opcode | Operand | What it does |
|---|---|---|---|
| 0 | `BRK` | | Ends a block of code. Also ends every argument, and the file |
| 1 | `NOP` | | |
| 2–5 | `PUSH`, `PUSHB`, `PUSHW`, `PUSHF` | 4, 1, 2, 4 | A literal: int32, int8, int16, float32 |
| 6, 7 | `PUSHA`, `PUSHS` | 4, 4 | Never seen in a shipped script |
| 8–10 | `PUSHSI`, `PUSHSIB`, `PUSHSIW` | 4, 1, 2 | A string literal, by index into the string pool |
| 11 | `PUSHI` | 4 | Never seen in a shipped script |
| 12–14 | `PUSHII`, `PUSHIIB`, `PUSHIIW` | 4, 1, 2 | An identifier, by index into the identifier pool |
| 15–17 | `PUSH0`, `PUSH1`, `PUSHM` | | The constants 0, 1 and -1 |
| 18 | `POP` | | Discards a value. Ends every expression statement |
| 19 | `RET` | | |
| 20–22 | `BRA`, `BF`, `BT` | 4 | Jump, jump if false, jump if true. The operand is signed and relative to the end of the instruction |
| 23 | `JSR` | 4 | Never seen in a shipped script |
| 24 | `CALL` | see below | |
| 25–33 | `ADD` `SUB` `MUL` `DIV` `SHL` `SHR` `AND` `OR` `XOR` | | |
| 34–41 | `LAND` `LOR` `EQ` `NE` `LT` `LE` `GT` `GE` | | |
| 42 | `ASSIGN` | | `=`, as an operator on the stack like any other |
| 43–46 | `PLUS`, `MINUS`, `INV`, `NOT` | | Unary `+ - ~ !` |
| 47, 48 | `BLK`, `ILLEGAL` | | Never seen in a shipped script |

The machine keeps no types. `PUSH0` serves for the integer 0 and the float
0.0 alike, which is why no shipped script ever pushes a float of 0, 1 or -1.

Seven opcodes in the table appear in no script the game ships, so nothing here
verifies what they do. The reader rejects them rather than guessing.

## A call

The one part of the format that is not obvious. Arguments are not evaluated
before the call: they are laid out after it as separate blocks of code, and
the call carries the address of each.

```
PUSHII  <name>            the function, by identifier index
CALL    <count>           then <count> uint32 addresses, one per argument
BRA     <over the args>   so execution skips the argument blocks
  ...code for argument 1, BRK
  ...code for argument 2, BRK
```

Each argument ends with `BRK`, which is what makes reading them back possible
at all: the reader can walk each argument's code from its address and know
where it stops. An expression statement ends with `POP` to discard the result.

## if and while

Both are built from `BF` and `BRA`, and are told apart by where the `BRA`
before the false branch jumps.

| Shape | `BRA` before the target | Reads back as |
|---|---|---|
| test, `BF`, body, `BRA` 0 | jumps nowhere | `if` with no `else` |
| test, `BF`, body, `BRA` forward | over the else | `if` / `else` |
| test, `BF`, body, `BRA` backward | to the test | `while` |

A `BRA` always follows the true half, even when there is no `else` and it
jumps nowhere. The game's own compiler emits it, and the reader needs it to
know where the block ends.

## QSC, the source language

Small enough to describe in a paragraph. Expression statements, `if` / `else`,
`while`, calls, the usual C operators, and four kinds of literal: int, hex,
float and string. There are no declarations, no functions, no `for`, no
`return`. Names may contain dots (`CutScene_3103.nTick`) and the whole thing
is one identifier, not a field access. Comments are `//` and `/* */`.

## Reading bytecode back

The code is a stack machine, so decompiling is a matter of replaying it with
an expression stack that holds syntax nodes instead of values. Operators pop
their operands and push a node; `CALL` walks each argument's code from its
recorded address; `BF` becomes an `if` or a `while` by the rule above.
Parentheses are reinserted only where operator priority needs them.

## What byte-for-byte costs

Reproducing the game's own files exactly, rather than merely producing
working ones, comes down to a handful of choices the format leaves open.

| Rule | Why |
|---|---|
| Both pools are in first use order | Any other order still runs, and changes every index in the file |
| 0, 1 and -1 use `PUSH0`, `PUSH1`, `PUSHM`, floats included | The wider forms work; the game never emits them |
| The narrow int pushes hold a **signed** value | `PUSHB` covers -128 to 127, so 242 needs `PUSHW`. The corpus shows `PUSHB` 2 to 127 and `PUSHW` 128 to 10000 |
| Pool indices are **unsigned**, and pick their width by index | A different rule from the one for literals, in the same shape of opcode |
| A negative literal is a unary minus, never a negative push | Which is how the reader writes it, so the two agree |
| Floats print as the shortest decimal that reads back identically | A 32 bit -0.4 is `-0.4000000059604645`, not the 17 digits `%.17g` gives |
| Strings are latin-1 | |
| The code ends with `BRK` | |

Matching the ToolKit's *decompilation* is a second problem, and a stranger
one: it means reproducing its pretty printer. Tabs for indent; a blank line
after an `else` and after a `while` body but not after the true half of an
`if`; call arguments wrapped at 300 characters, with a nested call starting on
a line of its own.

## How this is tested

The IGI ToolKit is the reference, captured once while it was still installed
and then retired. For every script the game ships,
[`corpus.py`](../studio/qvm/corpus.py) keeps three files: the original `.qvm`,
the ToolKit's decompilation of it, and the ToolKit's recompilation of that
decompilation.

[`check.py`](../studio/qvm/check.py) then holds our own code to it, in both
directions:

- **Reading** passes when our decompilation equals the ToolKit's, byte for byte.
- **Writing** passes when compiling the ToolKit's source gives back the game's
  own original file, byte for byte.

```
python -m studio check
```

All 884 scripts pass both. That is a stricter test than a round trip through
our own code, which would only prove the reader and writer agree with each
other: this one says they agree with the tool that made the files, and that
the bytes the game loads are reproduced exactly.

The corpus is derived from the game, so it is not in this repository. It is
rebuilt with `python -m studio corpus` on a machine with the game and the
ToolKit.

## What is not known

- The last two header words. Zero everywhere, so nothing says what they mean.
- `PUSHA`, `PUSHS`, `PUSHI`, `BT`, `JSR`, `BLK`, `ILLEGAL`. Named in the
  opcode table, absent from all 884 scripts. The reader raises on all seven.
- `RET` and `NOP` are read, but nothing in QSC emits them.
