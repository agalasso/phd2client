#!/usr/bin/env -S uv --quiet run --script
# /// script
# dependencies = [
#   "phd2client",
# ]
# ///
"""
Sample PHD2 python client demo
"""

import sys
import time

from phd2client.guider import Guider


def WaitForSettleDone(guider: Guider):
    while True:
        s = guider.CheckSettling()
        if s.Done:
            if s.Error:
                raise Exception(s.Error)
            print("settling is done")
            break
        print(
            f"settling dist {s.Distance:.1f}/{s.SettlePx:.1f} time {s.Time:.1f}/{s.SettleTime:.1f}"
        )
        time.sleep(1)


def main():
    host = "localhost"
    if len(sys.argv) > 1:
        host = sys.argv[1]

    with Guider(host) as guider:
        guider.Connect()

        # get the list of equipment profiles

        profiles = guider.GetEquipmentProfiles()

        for p in profiles:
            print(f"profile: {p}")

        # connect equipment in profile "Simulator"

        profile = "Simulator"
        print(f"connect profile {profile}")

        guider.ConnectEquipment(profile)

        # start guiding

        settlePixels = 2.0
        settleTime = 10.0
        settleTimeout = 100.0

        print("guide")

        guider.Guide(settlePixels, settleTime, settleTimeout)

        # wait for settling to complete

        WaitForSettleDone(guider)

        # monitor guiding for a little while

        for _ in range(0, 20):
            stats = guider.GetStats()
            state, avgDist = guider.GetStatus()
            print(
                f"{state} dist={avgDist:.1f} rms={stats.rms_tot:.1f} ({stats.rms_ra:.1f}, "
                f"{stats.rms_dec:.1f}) peak = {stats.peak_ra:.1f}, {stats.peak_dec:.1f}"
            )
            time.sleep(1)

        # dither

        ditherPixels = 3.0
        print("dither")
        guider.Dither(ditherPixels, settlePixels, settleTime, settleTimeout)

        # wait for settle

        WaitForSettleDone(guider)

        # stop guiding

        print("stop")

        guider.StopCapture()


if __name__ == "__main__":
    main()
