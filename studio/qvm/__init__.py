"""The game's script format (.qsc source, .qvm bytecode).

Reading and writing are ours, with no third party tool: they reproduce every
one of the 884 scripts the game ships, byte for byte.

  from studio.qvm import read, write
  q = read.parse("objects.qvm");  text = read.decompile(q)
  data = write.compile_text(text)
"""
