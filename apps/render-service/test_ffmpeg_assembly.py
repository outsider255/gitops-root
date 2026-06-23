import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

import ffmpeg_assembly as fa


def test_crossfade_cmd_uses_xfade_filter():
    cmd = fa.build_crossfade_loop_cmd("/assets/loops/42.mp4", "/tmp/looped_42.mp4")
    assert cmd[0] == "ffmpeg"
    assert "-filter_complex" in cmd
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "xfade" in filter_arg


def test_crossfade_cmd_inputs_the_same_file_twice():
    cmd = fa.build_crossfade_loop_cmd("/assets/loops/42.mp4", "/tmp/looped_42.mp4")
    assert cmd.count("/assets/loops/42.mp4") == 2


def test_crossfade_cmd_respects_fade_duration():
    cmd = fa.build_crossfade_loop_cmd("/assets/loops/42.mp4", "/tmp/looped_42.mp4", fade_duration_s=1.2)
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "duration=1.2" in filter_arg


def test_crossfade_cmd_ends_with_output_path():
    cmd = fa.build_crossfade_loop_cmd("/assets/loops/42.mp4", "/tmp/looped_42.mp4")
    assert cmd[-1] == "/tmp/looped_42.mp4"


def test_pingpong_cmd_uses_reverse_and_concat():
    cmd = fa.build_pingpong_loop_cmd("/assets/loops/43.mp4", "/tmp/looped_43.mp4")
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "reverse" in filter_arg
    assert "concat" in filter_arg


def test_pingpong_cmd_ends_with_output_path():
    cmd = fa.build_pingpong_loop_cmd("/assets/loops/43.mp4", "/tmp/looped_43.mp4")
    assert cmd[-1] == "/tmp/looped_43.mp4"


def test_ken_burns_cmd_uses_zoompan_filter():
    cmd = fa.build_ken_burns_cmd("/assets/stills/77.jpg", "/tmp/loop_77.mp4")
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "zoompan" in filter_arg


def test_ken_burns_cmd_sets_duration_via_loop_frames():
    cmd = fa.build_ken_burns_cmd("/assets/stills/77.jpg", "/tmp/loop_77.mp4", duration_s=8.0)
    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == "8.0"


def test_ken_burns_cmd_loops_the_still_input():
    cmd = fa.build_ken_burns_cmd("/assets/stills/77.jpg", "/tmp/loop_77.mp4")
    assert "-loop" in cmd
    assert cmd[cmd.index("-loop") + 1] == "1"


def test_ken_burns_cmd_respects_zoom_target():
    cmd = fa.build_ken_burns_cmd("/assets/stills/77.jpg", "/tmp/loop_77.mp4", zoom_target=1.25)
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "1.25" in filter_arg


def test_pick_random_overlay_returns_a_file_from_dir(tmp_path):
    (tmp_path / "rain.mp4").write_bytes(b"x")
    (tmp_path / "snow.mp4").write_bytes(b"x")
    picked = fa.pick_random_overlay(str(tmp_path))
    assert picked in (str(tmp_path / "rain.mp4"), str(tmp_path / "snow.mp4"))


def test_pick_random_overlay_raises_on_empty_dir(tmp_path):
    import pytest
    with pytest.raises(fa.NoOverlaysAvailable):
        fa.pick_random_overlay(str(tmp_path))


def test_pick_random_overlay_raises_on_nonexistent_dir(tmp_path):
    import pytest
    with pytest.raises(fa.NoOverlaysAvailable):
        fa.pick_random_overlay(str(tmp_path / "does_not_exist"))


def test_overlay_composite_cmd_uses_screen_blend():
    cmd = fa.build_overlay_composite_cmd(
        "/tmp/loop_77.mp4", "/assets/overlays/rain.mp4", None, "/tmp/composited.mp4"
    )
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "blend=all_mode=screen" in filter_arg


def test_overlay_composite_cmd_includes_qr_overlay_when_provided():
    cmd = fa.build_overlay_composite_cmd(
        "/tmp/loop_77.mp4", "/assets/overlays/rain.mp4", "/tmp/qr.png", "/tmp/composited.mp4"
    )
    assert "/tmp/qr.png" in cmd
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "overlay" in filter_arg


def test_overlay_composite_cmd_skips_qr_input_when_none():
    cmd = fa.build_overlay_composite_cmd(
        "/tmp/loop_77.mp4", "/assets/overlays/rain.mp4", None, "/tmp/composited.mp4"
    )
    assert "/tmp/qr.png" not in cmd
