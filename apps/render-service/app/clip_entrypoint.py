"""Entrypoint for the Shorts clip Job container. Invoked as:
python3 clip_entrypoint.py <loop_path> <track_path> <focal_x> <focal_y> <audio_start_s> <audio_duration_s> <output_path>"""
import subprocess
import sys
import tempfile
import os

import ffmpeg_assembly as fa


def main(loop_path, track_path, focal_x, focal_y, audio_start_s, audio_duration_s, output_path):
    with tempfile.TemporaryDirectory() as tmp:
        cropped_path = os.path.join(tmp, "cropped.mp4")
        subprocess.run(
            fa.build_vertical_crop_cmd(loop_path, cropped_path, float(focal_x), float(focal_y)),
            check=True, capture_output=True, timeout=60,
        )

        trimmed_audio_path = os.path.join(tmp, "clip_audio.mp3")
        subprocess.run(
            fa.build_audio_trim_cmd(track_path, trimmed_audio_path, float(audio_start_s), float(audio_duration_s)),
            check=True, capture_output=True, timeout=60,
        )

        repeat_count = fa.repeat_count_for_target_duration(8.0, float(audio_duration_s))
        inputs_txt_path = os.path.join(tmp, "inputs.txt")
        with open(inputs_txt_path, "w") as f:
            f.write(fa.build_inputs_manifest(cropped_path, repeat_count))

        subprocess.run(
            fa.build_concat_cmd(inputs_txt_path, trimmed_audio_path, output_path),
            check=True, capture_output=True, timeout=60,
        )

    print(f"clip complete: {output_path}")


if __name__ == "__main__":
    main(*sys.argv[1:8])
