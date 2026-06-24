import json
import sys
import traceback
from pathlib import Path

from src.visio_postprocess import move_lane_labels_to_left


if __name__ == "__main__":
    try:
        vsdx_path = Path(sys.argv[1]).resolve()

        # Accept either JSON list or plain args
        if len(sys.argv) == 3 and sys.argv[2].strip().startswith("["):
            lane_names = json.loads(sys.argv[2])
        else:
            lane_names = sys.argv[2:]

        fixed_path = move_lane_labels_to_left(vsdx_path, lane_names)
        print(f"FIXED_FILE={fixed_path}")

    except Exception:
        traceback.print_exc()
        sys.exit(1)