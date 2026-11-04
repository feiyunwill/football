"""Independent Schema15 study audit derived from the frozen Schema13 template."""
from pathlib import Path


def main():
  here = Path(__file__).resolve().parent
  template = here / 'audit_o23_schema13_entropy_midpoint_finisher_study.py'
  source = template.read_text()
  for old, new in (
      ('Schema13', 'Schema15'), ('schema13', 'schema15'),
      ('entropy-midpoint', 'firststep-entropy'), ('entropy_midpoint', 'firststep_entropy'),
      ('2v1_broad_entropy_midpoint_finisher', '2v1_broad_firststep_entropy_finisher'),
      ("protocol['payload_schema']==13", "protocol['payload_schema']==15"),
      ("int.from_bytes(checkpoint.read_bytes()[44:48],'little')==13", "int.from_bytes(checkpoint.read_bytes()[44:48],'little')==15"),
      ("native_start(Path(model['path']),seed,13,8192)", "native_start(Path(model['path']),seed,15,8192)"),
  ):
    source = source.replace(old, new)
  namespace = {'__name__': '__main__', '__file__': str(Path(__file__).resolve())}
  exec(compile(source, namespace['__file__'], 'exec'), namespace)


if __name__ == '__main__':
  main()
