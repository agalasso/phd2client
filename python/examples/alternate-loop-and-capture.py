#!/usr/bin/env -S uv --quiet run --script
# /// script
# dependencies = [
#   "phd2client>=0.3.0",
# ]
# ///
"""
capture_single_frame demo
"""

import os
import time

from phd2client.guider import Guider, Subframe


def main():
    with Guider(connect=True) as guider:
        # connect equipment if not already connected
        print("connect equipment")
        guider.Call("set_connected", True)

        # single frame capture params
        single_frame_exposure_ms = 1000
        single_frame_binning = 1
        single_frame_gain = 88
        single_frame_roi = None
        single_frame_path = "/tmp/foo.fit"
        single_frame_limit_frame = None

        # guiding capture params com from the profile in PHD2
        guiding_limit_frame = Subframe(400, 100, 500, 500)

        for _ in range(3):
            # capture single frame using full frame
            guider.SetLimitFrame(roi=single_frame_limit_frame)

            # capture must be stopped before calling capture_single_frame

            guider.StopCapture()
            print(f"capture single frame {single_frame_exposure_ms}ms")
            # capture_single_frame path must not already exist
            try:
                os.remove(single_frame_path)
            except FileNotFoundError:
                pass

            guider.CaptureSingleFrame(
                exposure=single_frame_exposure_ms,
                binning=single_frame_binning,
                gain=single_frame_gain,
                roi=single_frame_roi,
                path=single_frame_path,
            )
            wait_for_completion(guider)

            # loop exposures using a limit frame
            guider.SetLimitFrame(roi=guiding_limit_frame)

            guider.Loop()

            # wait for a few frames
            prev_frame = None
            frame_count = 0
            while True:
                time.sleep(0.5)
                if (frame := guider.FrameNum) is None:
                    continue
                if prev_frame is None:
                    prev_frame = frame
                    frame_count = 1
                else:
                    frame_count += frame - prev_frame
                print(f"{frame_count=}")
                if frame_count >= 2:
                    break
                prev_frame = frame

        guider.StopCapture()


def wait_for_completion(guider: Guider):
    # wait for exposure to complete
    time.sleep(guider.GetExposure() / 1000)

    # wait for completion notification
    deadline = time.monotonic() + 10
    while True:
        if result := guider.CheckSingleFrame():
            print(f"result ok={result.success}")
            if result.success:
                print(f"  path = {result.path}")
            else:
                print(f"  error: {result.error_message}")
            break
        time.sleep(0.5)
        if time.monotonic() > deadline:
            raise Exception("timed-out waiting for single exposure to complete!")


if __name__ == "__main__":
    main()
