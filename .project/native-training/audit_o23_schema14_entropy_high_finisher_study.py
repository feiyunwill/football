"""Independent Schema14 study audit derived from a separately frozen schema-neutral template."""
from pathlib import Path


def main():
  here = Path(__file__).resolve().parent
  template = here / 'audit_o23_schema13_entropy_midpoint_finisher_study.py'
  source = template.read_text()
  for old, new in (
      ('Schema13', 'Schema14'), ('schema13', 'schema14'),
      ('entropy-midpoint', 'entropy-high'), ('entropy_midpoint', 'entropy_high'),
      ('2v1_broad_entropy_midpoint_finisher', '2v1_broad_entropy_high_finisher'),
      ("protocol['payload_schema']==13", "protocol['payload_schema']==14"),
      ("int.from_bytes(checkpoint.read_bytes()[44:48],'little')==13", "int.from_bytes(checkpoint.read_bytes()[44:48],'little')==14"),
      ("native_start(Path(model['path']),seed,13,8192)", "native_start(Path(model['path']),seed,14,8192)"),
  ):
    source = source.replace(old, new)
  namespace = {'__name__': '__main__', '__file__': str(Path(__file__).resolve())}
  exec(compile(source, namespace['__file__'], 'exec'), namespace)


if __name__ == '__main__':
  main()
