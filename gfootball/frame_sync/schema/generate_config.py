# Copyright 2019 Google LLC
# 从 schema/constants.yaml 生成 gfootball/frame_sync/config.py（常量单一来源）

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import sys

def main():
  try:
    import yaml
  except ImportError:
    sys.stderr.write("run: pip install pyyaml\n")
    sys.exit(1)
  schema_dir = os.path.dirname(os.path.abspath(__file__))
  yaml_path = os.path.join(schema_dir, "constants.yaml")
  with open(yaml_path, "r") as f:
    data = yaml.safe_load(f)
  out_dir = os.path.join(os.path.dirname(schema_dir), "..")
  config_path = os.path.join(out_dir, "frame_sync", "config.py")
  with open(config_path, "w") as f:
    f.write(
      "# Generated from gfootball/frame_sync/schema/constants.yaml - do not edit by hand\n"
      "# Copyright 2019 Google LLC\n\n"
      "from __future__ import absolute_import\n"
      "from __future__ import division\n"
      "from __future__ import print_function\n\n"
      "FRAME_INPUT_TIMEOUT_MS = %s\n"
      "MAX_PREDICT_AHEAD_FRAMES = %s\n"
      "MAX_FRAMES_WITHOUT_PACKET = %s\n"
      "STATE_HASH_INTERVAL_K = %s\n"
      % (
        data["frame_input_timeout_ms"],
        data["max_predict_ahead_frames"],
        data["max_frames_without_packet"],
        data["state_hash_interval_k"],
      )
    )
  print("Wrote %s" % config_path)

if __name__ == "__main__":
  main()
