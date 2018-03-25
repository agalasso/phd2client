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
using Newtonsoft.Json.Linq;

namespace guider
{
    // settling progress information returned by Guider::CheckSettling()
    public class SettleProgress
    {
        public bool Done;
        public double Distance;
        public double SettlePx;
        public double Time;
        public double SettleTime;
        public int Status;
        public string Error;
    }

    public class GuideStats
    {
        public double rms_tot;
        public double rms_ra;
        public double rms_dec;
        public double peak_ra;
        public double peak_dec;

        public GuideStats Clone() { return (GuideStats) MemberwiseClone(); }
    }

    public class GuiderException : System.ApplicationException
    {
        public GuiderException(string message) : base(message) { }
        public GuiderException(string message, System.Exception inner) : base(message, inner) { }
    }

    public abstract class Guider : IDisposable
    {
        public static Guider Factory(string hostname, uint phd2_instance = 1) { return new GuiderImpl(hostname, phd2_instance); }

        public abstract void Dispose();

        // connect to PHD2 -- you'll need to call Connect before calling any of the server API methods below
        public abstract void Connect();

        // disconnect from PHD2
        public abstract void Close();

        // these two member functions are for raw JSONRPC method invocation. Generally you won't need to
        // use these functions as it is much more convenient to use the higher-level methods below
        public abstract JObject Call(string method);
        public abstract JObject Call(string method, JToken param);

        // Start guiding with the given settling parameters. PHD2 takes care of looping exposures,
        // guide star selection, and settling. Call CheckSettling() periodically to see when settling
        // is complete.
        public abstract void Guide(double settlePixels, double settleTime, double settleTimeout);

        // Dither guiding with the given dither amount and settling parameters. Call CheckSettling()
        // periodically to see when settling is complete.
        public abstract void Dither(double ditherPixels, double settlePixels, double settleTime, double settleTimeout);

        // Check if phd2 is currently in the process of settling after a Guide or Dither
        public abstract bool IsSettling();

        // Get the progress of settling
        public abstract SettleProgress CheckSettling();

        // Get the guider statistics since guiding started. Frames captured while settling is in progress
        // are excluded from the stats.
        public abstract GuideStats GetStats();

        // stop looping and guiding
        public abstract void StopCapture(uint timeoutSeconds = 10);

        // start looping exposures
        public abstract void Loop(uint timeoutSeconds = 10);

        // get the guider pixel scale in arc-seconds per pixel
        public abstract double PixelScale();

        // get a list of the Equipment Profile names
        public abstract List<string> GetEquipmentProfiles();

        // connect the equipment in an equipment profile
        public abstract void ConnectEquipment(string profileName);

        // disconnect equipment
        public abstract void DisconnectEquipment();

        // get the AppState (https://github.com/OpenPHDGuiding/phd2/wiki/EventMonitoring#appstate)
        // and current guide error
        public abstract void GetStatus(out string appState, out double avgDist);

        // check if currently guiding
        public abstract bool IsGuiding();

        // pause guiding (looping exposures continues)
        public abstract void Pause();

        // un-pause guiding
        public abstract void Unpause();

        // save the current guide camera frame (FITS format), returning the name of the file.
        // The caller will need to remove the file when done.
        public abstract string SaveImage();
    }
}
