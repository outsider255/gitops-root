"""Entrypoint for the real assembly Job container. Invoked as:
python3 assembly_entrypoint.py <loop_path> <track_path> <category> <output_path>
Chains Tasks 5-8's command builders and actually runs them via subprocess
(this file, unlike ffmpeg_assembly.py's pure builders, is the one place
that executes ffmpeg for real)."""
import subprocess
import sys
import tempfile
import os

import ffmpeg_assembly as fa

TRACK_TARGET_DURATION_S = 240.0
LOOP_DURATION_S = 8.0


def main(loop_path: str, track_path: str, category: str, output_path: str):
    with tempfile.TemporaryDirectory() as tmp:
        looped_path = os.path.join(tmp, "looped.mp4")
        subprocess.run(
            fa.build_crossfade_loop_cmd(loop_path, looped_path),
            check=True, capture_output=True, timeout=120,
        )

        try:
            overlay_path = fa.pick_random_overlay()
            composited_path = os.path.join(tmp, "composited.mp4")
            subprocess.run(
                fa.build_overlay_composite_cmd(looped_path, overlay_path, None, composited_path),
                check=True, capture_output=True, timeout=120,
            )
        except fa.NoOverlaysAvailable:
            composited_path = looped_path

        repeat_count = fa.repeat_count_for_target_duration(LOOP_DURATION_S, TRACK_TARGET_DURATION_S)
        inputs_txt_path = os.path.join(tmp, "inputs.txt")
        with open(inputs_txt_path, "w") as f:
            f.write(fa.build_inputs_manifest(composited_path, repeat_count))

        subprocess.run(
            fa.build_concat_cmd(inputs_txt_path, track_path, output_path),
            check=True, capture_output=True, timeout=60,
        )

    print(f"assembly complete: {output_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
