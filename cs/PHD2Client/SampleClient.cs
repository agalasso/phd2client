/*

MIT License

Copyright (c) 2018 Andy Galasso

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

using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using guider;

namespace PHD2Client
{
    class SampleClient
    {
        static void WaitForSettleDone(Guider guider)
        {
            while (true)
            {
                SettleProgress s = guider.CheckSettling();

                if (s.Done)
                {
                    System.Console.WriteLine("settling is done");
                    break;
                }

                System.Console.WriteLine("settling dist {0:F1}/{1:F1}  time {2:F1}/{3:F1}",
                       s.Distance, s.SettlePx, s.Time, s.SettleTime);

                System.Threading.Thread.Sleep(1000);
            }
        }

        static void Main(string[] args)
        {
            string host = "localhost";
            if (args.Length > 0)
                host = args[0];

            try
            {
                using (Guider guider = Guider.Factory(host))
                {
                    // connect to PHD2

                    guider.Connect();

                    // get the list of equipment profiles

                    foreach (var p in guider.GetEquipmentProfiles())
                    {
                        Console.WriteLine("profile: {0}", p);
                    }

                    // connect equipment in profile "Simulator"

                    string profile = "Simulator";
                    Console.WriteLine("connect profile {0}", profile);

                    guider.ConnectEquipment(profile);

                    // start guiding

                    double settlePixels = 2.0;
                    double settleTime = 10.0;
                    double settleTimeout = 100.0;

                    Console.WriteLine("guide");

                    guider.Guide(settlePixels, settleTime, settleTimeout);

                    // wait for settling to complete

                    WaitForSettleDone(guider);

                    // monitor guiding for a little while

                    for (int i = 0; i < 15; i++)
                    {
                        GuideStats stats = guider.GetStats();

                        string state;
                        double avgDist;
                        guider.GetStatus(out state, out avgDist);

                        Console.WriteLine("{0} dist={1:F1} rms={2:F1} ({3:F1}, {4:F1}) peak = {5:F1}, {6:F1}",
                               state, avgDist,
                               stats.rms_tot, stats.rms_ra, stats.rms_dec, stats.peak_ra, stats.peak_dec);

                        System.Threading.Thread.Sleep(1000);
                    }

                    // Pause/resume guiding

                    Console.WriteLine("pause for 5s");
                    guider.Pause();
                    System.Threading.Thread.Sleep(5000);
                    Console.WriteLine("un-pause");
                    guider.Unpause();

                    // dither

                    double ditherPixels = 3.0;

                    Console.WriteLine("dither");

                    guider.Dither(ditherPixels, settlePixels, settleTime, settleTimeout);

                    // wait for settle

                    WaitForSettleDone(guider);

                    // stop guiding

                    Console.WriteLine("stop\n");

                    guider.StopCapture();

                    // disconnect from PHD2 (optional in this case since we've got a using() block to take care of it)
                    guider.Close();
                }
            }
            catch (Exception err)
            {
                Console.WriteLine("Error: {0}", err.Message);
            }
        }
    }
}
