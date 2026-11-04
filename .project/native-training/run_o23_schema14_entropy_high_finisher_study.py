"""Frozen Schema14 five-seed study derived from a separately frozen schema-neutral template."""
from pathlib import Path


def main():
  here = Path(__file__).resolve().parent
  template = here / 'run_o23_schema13_entropy_midpoint_finisher_study.py'
  source = template.read_text()
  for old, new in (
      ('Schema13', 'Schema14'), ('schema13', 'schema14'),
      ('entropy-midpoint', 'entropy-high'), ('entropy_midpoint', 'entropy_high'),
      ('2v1_broad_entropy_midpoint_finisher', '2v1_broad_entropy_high_finisher'),
      ('payload_schema=13', 'payload_schema=14'),
      ('starts_binary,13,seed', 'starts_binary,14,seed'),
      ('native_start(last_checkpoint,seed,13,8192)', 'native_start(last_checkpoint,seed,14,8192)'),
      ("o23-schema14-entropy-high-finisher-budget-20261029-v2.md", "o23-schema14-entropy-high-finisher-budget-20261029.md"),
      ("files=[Path(__file__),auditor,helper", "files=[Path(__file__),Path(__file__).with_name('run_o23_schema13_entropy_midpoint_finisher_study.py'),Path(__file__).with_name('audit_o23_schema13_entropy_midpoint_finisher_study.py'),auditor,helper"),
  ):
    source = source.replace(old, new)
  namespace = {'__name__': '__main__', '__file__': str(Path(__file__).resolve())}
  exec(compile(source, namespace['__file__'], 'exec'), namespace)


if __name__ == '__main__':
  main()
