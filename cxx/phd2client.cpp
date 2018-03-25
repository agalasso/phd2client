/*

MIT License

Copyright (c) 2017 Andy Galasso

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

*/

#include "guider.h"

#include <stdio.h>
#include <thread>

static void WaitForSettleDone(Guider& guider)
{
    while (1)
    {
        SettleProgress s;
        if (!guider.CheckSettling(&s))
            throw guider.LastError();

        if (s.Done)
        {
            printf("settling is done\n");
            break;
        }

        printf("settling dist %.1f/%.1f  time %.1f/%.1f\n",
               s.Distance, s.SettlePx, s.Time, s.SettleTime);

        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
}

int main(int argc, char *argv[])
{
    const char *host = "localhost";
    if (argc > 1)
        host = argv[1];

    Guider guider(host);

    try
    {
        // connect to PHD2

        if (!guider.Connect())
            throw guider.LastError();

        // get the list of equipment profiles

        std::vector<std::string> profiles;
        if (!guider.GetEquipmentProfiles(&profiles))
            throw guider.LastError();

        for (auto p : profiles)
        {
            printf("profile: %s\n", p.c_str());
        }

        // connect equipment in profile "Simulator"

        const char *profile = "Simulator";
        printf("connect profile %s\n", profile);

        if (!guider.ConnectEquipment(profile))
            throw guider.LastError();

        // start guiding

        double settlePixels = 2.0;
        double settleTime = 10.0;
        double settleTimeout = 100.0;

        printf("guide\n");

        if (!guider.Guide(settlePixels, settleTime, settleTimeout))
            throw guider.LastError();

        // wait for settling to complete

        WaitForSettleDone(guider);

        // monitor guiding for a little while

        for (int i = 0; i < 20; i++)
        {
            GuideStats stats;
            if (!guider.GetStats(&stats))
                throw guider.LastError();

            std::string state;
            double avgDist;
            if (!guider.GetStatus(&state, &avgDist))
                throw guider.LastError();

            printf("%s dist=%.1f rms=%.1f (%.1f, %.1f) peak = %.1f, %.1f\n",
                   state.c_str(), avgDist,
                   stats.rms_tot, stats.rms_ra, stats.rms_dec, stats.peak_ra, stats.peak_dec);

            std::this_thread::sleep_for(std::chrono::seconds(1));
        }

        // dither

        double ditherPixels = 3.0;

        printf("dither\n");

        if (!guider.Dither(ditherPixels, settlePixels, settleTime, settleTimeout))
            throw guider.LastError();

        // wait for settle

        WaitForSettleDone(guider);

        // stop guiding

        printf("stop\n");

        if (!guider.StopCapture())
            throw guider.LastError();
    }
    catch (const std::string& err)
    {
        fprintf(stderr, "Error: %s\n", err.c_str());
        exit(1);
    }

    return 0;
}
