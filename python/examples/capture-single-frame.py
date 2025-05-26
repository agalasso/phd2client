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

        # stop looping exposures in case not stopped already
        print("stop capture")
        guider.StopCapture()

        # example: save image to a specific path
        exposure_ms = 5432
        binning = 2
        gain = 88
        roi = Subframe(x=30, y=30, width=100, height=100)
        path = "/tmp/foo.fit"
        # path must not already exist
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

        print(f"capture single frame {exposure_ms}ms")
        guider.CaptureSingleFrame(
            exposure=exposure_ms,
            binning=binning,
            gain=gain,
            roi=roi,
            path=path,
        )
        wait_for_completion(guider)

        # example: save image but let phd2 choose the path
        exposure_ms = 2000
        binning = None  # default binning
        gain = None  # default gain
        roi = None  # full frame

        print(f"capture single frame {exposure_ms}")
        guider.CaptureSingleFrame(
            exposure=exposure_ms,
            binning=binning,
            gain=gain,
            roi=roi,
            save=True,
        )
        wait_for_completion(guider)


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
