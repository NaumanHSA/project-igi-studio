# Third party notices

Project IGI Studio is MIT licensed (see `LICENSE`). It includes or derives from
the following third party work.

## three.js

`editor/vendor/three.module.min.js` and `editor/vendor/OrbitControls.js`
Copyright (c) 2010 three.js authors, MIT licensed.
See `editor/vendor/three-LICENSE.txt`.

## project-igi-editor

<https://github.com/HeavenHM/project-igi-editor>
Copyright (c) 2026 HeavenHM, MIT licensed.

Our QVM reader and writer (`studio/qvm/read.py`, `studio/qvm/write.py` and the
QSC lexer and parser beside them) are ported from its C++ parsers, and its
written specification of the `LOOP 8.5` header, the string pools and the 49
opcodes. Each ported file names it in its header.

```
MIT License

Copyright (c) 2026 HeavenHM

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## IGI research data

<https://github.com/IGI-Research-Devs/IGI-Research-Data>

`studio/extract/model_names.json` is the community's table of model ids and
names (the ToolKit's `IGIModels.txt`), kept here so that nothing else has to
be installed to see a building called a building. Credit to the IGI Research
Devs, who ask for exactly that. The studio still reads a local copy of their
file when one is installed, for anything the table does not have.

## The IGI ToolKit

<https://github.com/IGI-Research-Devs> Not shipped and not linked against.
Until our own compiler passes on the whole corpus, building a mission calls
`gconv.exe` and `dconv.exe` from a ToolKit installation on the user's machine.
Once Phase 3 of `docs/PLAN-ship.md` is done, that dependency is gone.

## The game

Project I.G.I.: I'm Going In is the property of its owners. This project ships
no game files and no game-derived data. Everything it needs is produced on your
own machine from your own copy of the game.
