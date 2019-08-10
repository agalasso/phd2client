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
using System.Diagnostics;
using System.Linq;
using System.Text;
using System.IO;
using System.Net.Sockets;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace guider
{
    class GuiderConnection : IDisposable
    {
        TcpClient tcpCli;
        StreamWriter sw;
        StreamReader sr;

        public GuiderConnection()
        {
        }

        public bool Connect(string hostname, ushort port)
        {
            try
            {
                tcpCli = new TcpClient(hostname, port);
                sw = new StreamWriter(tcpCli.GetStream());
                sw.AutoFlush = true;
                sw.NewLine = "\r\n";
                sr = new StreamReader(tcpCli.GetStream());
                return true;
            }
            catch (Exception)
            {
                Close();
                return false;
            }
        }

        public void Dispose()
        {
            Close();
        }

        public void Close()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        protected virtual void Dispose(bool disposing)
        {
            if (disposing)
            {
                if (sw != null)
                {
                    sw.Close();
                    sw.Dispose();
                    sw = null;
                }
                if (sr != null)
                {
                    sr.Close();
                    sr.Dispose();
                    sr = null;
                }
                if (tcpCli != null)
                {
                    Debug.WriteLine("Disconnect from phd2");
                    tcpCli.Close();
                    tcpCli = null;
                }
            }
        }

        public bool IsConnected
        {
            get {
                return tcpCli != null && tcpCli.Connected;
            }
        }

        public string ReadLine()
        {
            try
            {
                return sr.ReadLine();
            }
            catch (Exception)
            {
                // phd2 disconnected
                return null;
            }
        }

        public void WriteLine(string s)
        {
            sw.WriteLine(s);
        }

        public void Terminate()
        {
            if (tcpCli != null)
                tcpCli.Close();
        }
    }

    class Accum
    {
        uint n;
        double a;
        double q;
        double peak;

        public Accum() {
            Reset();
        }
        public void Reset() {
            n = 0;
            a = q = peak = 0;
        }
        public void Add(double x) {
            double ax = Math.Abs(x);
            if (ax > peak) peak = ax;
            ++n;
            double d = x - a;
            a += d / (double) n;
            q += (x - a) * d;
        }
        public double Mean() {
            return a;
        }
        public double Stdev() {
            return n >= 1 ? Math.Sqrt(q / (double) n) : 0.0;
        }
        public double Peak() {
            return peak;
        }
    }

    class GuiderImpl : Guider
    {
        string m_host;
        uint m_instance;
        GuiderConnection m_conn;
        System.Threading.Thread m_worker;
        bool m_terminate;
        readonly object m_sync = new object();
        JObject m_response;
        Accum accum_ra = new Accum();
        Accum accum_dec = new Accum();
        bool accum_active;
        double settle_px;
        string AppState;
        double AvgDist;
        GuideStats Stats;
        string Version;
        string PHDSubver;
        SettleProgress mSettle;

        private void _Worker()
        {
            try
            {
                while (!m_terminate)
                {
                    string line = m_conn.ReadLine();
                    if (line == null)
                    {
                        // phd2 disconnected
                        // todo: re-connect (?)
                        break;
                    }

                    Debug.WriteLine(String.Format("L: {0}", line));

                    JObject j;
                    try
                    {
                        j = JObject.Parse(line);
                    }
                    catch (JsonReaderException ex)
                    {
                        Debug.WriteLine(String.Format("ignoring invalid json from server: {0}: {1}", ex.Message, line));
                        continue;
                    }

                    if (j.ContainsKey("jsonrpc"))
                    {
                        // a response
                        Debug.WriteLine(String.Format("R: {0}", line));
                        lock (m_sync)
                        {
                            m_response = j;
                            System.Threading.Monitor.Pulse(m_sync);
                        }
                    }
                    else
                    {
                        handle_event(j);
                    }
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine(String.Format("caught exception in worker thread: {0}", ex.ToString()));
            }
            finally
            {
                m_conn.Terminate();
            }
        }

        private static void Worker(Object obj)
        {
            GuiderImpl impl = (GuiderImpl)obj;
            impl._Worker();
        }

        private void handle_event(JObject ev)
        {
            string e = (string) ev["Event"];

            if (e == "AppState")
            {
                lock (m_sync)
                {
                    AppState = (string) ev["State"];
                    if (is_guiding(AppState))
                        AvgDist = 0.0;   // until we get a GuideStep event
                }
            }
            else if (e == "Version")
            {
                lock (m_sync)
                {
                    Version = (string) ev["PHDVersion"];
                    PHDSubver = (string) ev["PHDSubver"];
                }
            }
            else if (e == "StartGuiding")
            {
                accum_active = true;
                accum_ra.Reset();
                accum_dec.Reset();

                GuideStats stats = accum_get_stats(accum_ra, accum_dec);

                lock (m_sync)
                {
                    Stats = stats;
                }
            }
            else if (e == "GuideStep")
            {
                GuideStats stats = null;
                if (accum_active)
                {
                    accum_ra.Add((double) ev["RADistanceRaw"]);
                    accum_dec.Add((double) ev["DECDistanceRaw"]);
                    stats = accum_get_stats(accum_ra, accum_dec);
                }

                lock (m_sync)
                {
                    AppState = "Guiding";
                    AvgDist = (double) ev["AvgDist"];
                    if (accum_active)
                        Stats = stats;
                }
            }
            else if (e == "SettleBegin")
            {
                accum_active = false;  // exclude GuideStep messages from stats while settling
            }
            else if (e == "Settling")
            {
                SettleProgress s = new SettleProgress();
                s.Done = false;
                s.Distance = (double) ev["Distance"];
                s.SettlePx = settle_px;
                s.Time = (double) ev["Time"];
                s.SettleTime = (double) ev["SettleTime"];
                s.Status = 0;
                lock (m_sync)
                {
                    mSettle = s;
                }
            }
            else if (e == "SettleDone")
            {
                accum_active = true;
                accum_ra.Reset();
                accum_dec.Reset();

                GuideStats stats = accum_get_stats(accum_ra, accum_dec);

                SettleProgress s = new SettleProgress();
                s.Done = true;
                s.Status = (int) ev["Status"];
                s.Error = (string) ev["Error"];

                lock (m_sync)
                {
                    mSettle = s;
                    Stats = stats;
                }
            }
            else if (e == "Paused")
            {
                lock (m_sync)
                {
                    AppState = "Paused";
                }
            }
            else if (e == "StartCalibration")
            {
                lock (m_sync)
                {
                    AppState = "Calibrating";
                }
            }
            else if (e == "LoopingExposures")
            {
                lock (m_sync)
                {
                    AppState = "Looping";
                }
            }
            else if (e == "LoopingExposuresStopped" || e == "GuidingStopped")
            {
                lock (m_sync)
                {
                    AppState = "Stopped";
                }
            }
            else if (e == "StarLost")
            {
                lock (m_sync)
                {
                    AppState = "LostLock";
                    AvgDist = (double) ev["AvgDist"];
                }
            }
            else
            {
                Debug.WriteLine(String.Format("todo: handle event {0}", e));
            }
        }

        static string make_jsonrpc(string method, JToken param)
        {
            JObject req = new JObject();

            req["method"] = method;
            req["id"] = 1;

            if (param != null && param.Type != JTokenType.Null)
            {
                if (param.Type == JTokenType.Array || param.Type == JTokenType.Object)
                    req["params"] = param;
                else
                {
                    // single non-null parameter
                    JArray ary = new JArray();
                    ary.Add(param);
                    req["params"] = ary;
                }
            }

            return req.ToString(Formatting.None);
        }

        static bool failed(JObject res)
        {
            return res.ContainsKey("error");
        }

        public GuiderImpl(string hostname, uint phd2_instance)
        {
            m_host = hostname;
            m_instance = phd2_instance;
            m_conn = new GuiderConnection();
        }

        public override void Close()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        public override void Dispose()
        {
            Close();
        }

        protected virtual void Dispose(bool disposing)
        {
            if (disposing)
            {
                if (m_worker != null)
                {
                    m_terminate = true;
                    m_conn.Terminate();
                    m_worker.Join();
                    m_worker = null;
                }

                m_conn.Close();
            }
        }

        // connect to PHD2 -- you'll need to call Connect before calling any of the server API methods below
        public override void Connect()
        {
            Close();

            ushort port = (ushort)(4400 + m_instance - 1);
            if (!m_conn.Connect(m_host, port))
                throw new GuiderException(String.Format("Could not connect to PHD2 instance {0} on {1}", m_instance, m_host));

            m_terminate = false;

            System.Threading.Thread thr = new System.Threading.Thread(Worker);
            thr.Start(this);
            m_worker = thr;
        }

        static GuideStats accum_get_stats(Accum ra, Accum dec)
        {
            GuideStats stats = new GuideStats();
            stats.rms_ra = ra.Stdev();
            stats.rms_dec = dec.Stdev();
            stats.peak_ra = ra.Peak();
            stats.peak_dec = dec.Peak();
            return stats;
        }

        static bool is_guiding(string st)
        {
            return st == "Guiding" || st == "LostLock";
        }

        // these two member functions are for raw JSONRPC method invocation. Generally you won't need to
        // use these functions as it is much more convenient to use the higher-level methods below
        public override JObject Call(string method)
        {
            return Call(method, null);
        }

        public override JObject Call(string method, JToken param)
        {
            string s = make_jsonrpc(method, param);
            Debug.WriteLine(String.Format("Call: {0}", s));

            // send request
            m_conn.WriteLine(s);

            // wait for response

            lock (m_sync)
            {
                while (m_response == null)
                    System.Threading.Monitor.Wait(m_sync);

                JObject response = m_response;
                m_response = null;

                if (failed(response))
                    throw new GuiderException((string) response["error"]["message"]);

                return response;
            }
        }

        static JObject SettleParam(double settlePixels, double settleTime, double settleTimeout)
        {
            JObject s = new JObject();
            s["pixels"] = settlePixels;
            s["time"] = settleTime;
            s["timeout"] = settleTimeout;
            return s;
        }

        void CheckConnected()
        {
            if (!m_conn.IsConnected)
                throw new GuiderException("PHD2 Server disconnected");
        }

        // Start guiding with the given settling parameters. PHD2 takes care of looping exposures,
        // guide star selection, and settling. Call CheckSettling() periodically to see when settling
        // is complete.
        public override void Guide(double settlePixels, double settleTime, double settleTimeout)
        {
            CheckConnected();

            SettleProgress s = new SettleProgress();
            s.Done = false;
            s.Distance = 0.0;
            s.SettlePx = settlePixels;
            s.Time = 0.0;
            s.SettleTime = settleTime;
            s.Status = 0;

            lock (m_sync)
            {
                if (mSettle != null && !mSettle.Done)
                    throw new GuiderException("cannot guide while settling");
                mSettle = s;
            }

            try
            {
                JArray param = new JArray();
                param.Add(SettleParam(settlePixels, settleTime, settleTimeout));
                param.Add(false); // don't force calibration

                Call("guide", param);
                settle_px = settlePixels;
            }
            catch (Exception)
            {
                // failed - remove the settle state
                lock (m_sync)
                {
                    mSettle = null;
                }
                throw;
            }
        }

        // Dither guiding with the given dither amount and settling parameters. Call CheckSettling()
        // periodically to see when settling is complete.
        public override void Dither(double ditherPixels, double settlePixels, double settleTime, double settleTimeout)
        {
            CheckConnected();

            SettleProgress s = new SettleProgress();
            s.Done = false;
            s.Distance = ditherPixels;
            s.SettlePx = settlePixels;
            s.Time = 0.0;
            s.SettleTime = settleTime;
            s.Status = 0;

            lock (m_sync)
            {
                if (mSettle != null && !mSettle.Done)
                    throw new GuiderException("cannot dither while settling");

                mSettle = s;
            }

            try
            {
                JArray param = new JArray();
                param.Add(ditherPixels);
                param.Add(false);
                param.Add(SettleParam(settlePixels, settleTime, settleTimeout));

                Call("dither", param);
                settle_px = settlePixels;
            }
            catch (Exception)
            {
                // call failed - remove the settle state
                lock (m_sync)
                {
                    mSettle = null;
                }
                throw;
            }
        }

        // Check if phd2 is currently in the process of settling after a Guide or Dither
        public override bool IsSettling()
        {
            CheckConnected();

            lock (m_sync)
            {
                if (mSettle != null)
                {
                    return true;
                }
            }

            // for app init, initialize the settle state to a consistent value
            // as if Guide had been called

            JObject res = Call("get_settling");

            bool val = (bool) res["result"];

            if (val)
            {
                SettleProgress s = new SettleProgress();
                s.Done = false;
                s.Distance = -1.0;
                s.SettlePx = 0.0;
                s.Time = 0.0;
                s.SettleTime = 0.0;
                s.Status = 0;
                lock (m_sync)
                {
                    if (mSettle == null)
                        mSettle = s;
                }
            }

            return val;
        }

        // Get the progress of settling
        public override SettleProgress CheckSettling()
        {
            CheckConnected();

            SettleProgress ret = new SettleProgress();

            lock (m_sync)
            {
                if (mSettle == null)
                    throw new GuiderException("not settling");

                if (mSettle.Done)
                {
                    // settle is done
                    ret.Done = true;
                    ret.Status = mSettle.Status;
                    ret.Error = mSettle.Error;
                    mSettle = null;
                }
                else
                {
                    // settle in progress
                    ret.Done = false;
                    ret.Distance = mSettle.Distance;
                    ret.SettlePx = settle_px;
                    ret.Time = mSettle.Time;
                    ret.SettleTime = mSettle.SettleTime;
                }
            }

            return ret;
        }

        // Get the guider statistics since guiding started. Frames captured while settling is in progress
        // are excluded from the stats.
        public override GuideStats GetStats()
        {
            CheckConnected();

            GuideStats stats;
            lock (m_sync)
            {
                stats = Stats.Clone();
            }
            stats.rms_tot = Math.Sqrt(stats.rms_ra * stats.rms_ra + stats.rms_dec * stats.rms_dec);
            return stats;
        }

        // stop looping and guiding
        public override void StopCapture(uint timeoutSeconds)
        {
            Call("stop_capture");

            for (uint i = 0; i < timeoutSeconds; i++)
            {
                string appstate;
                lock (m_sync)
                {
                    appstate = AppState;
                }
                Debug.WriteLine(String.Format("StopCapture: AppState = {0}", appstate));
                if (appstate == "Stopped")
                    return;

                System.Threading.Thread.Sleep(1000);
                CheckConnected();
            }
            Debug.WriteLine("StopCapture: timed-out waiting for stopped");

            // hack! workaround bug where PHD2 sends a GuideStep after stop request and fails to send GuidingStopped
            JObject res = Call("get_app_state");
            string st = (string) res["result"];

            lock (m_sync)
            {
                AppState = st;
            }

            if (st == "Stopped")
                return;
            // end workaround

            throw new GuiderException(String.Format("guider did not stop capture after {0} seconds!", timeoutSeconds));
        }

        // start looping exposures
        public override void Loop(uint timeoutSeconds)
        {
            CheckConnected();

            // already looping?
            lock (m_sync)
            {
                if (AppState == "Looping")
                    return;
            }

            JObject res = Call("get_exposure");
            int exp = (int) res["result"];

            Call("loop");

            System.Threading.Thread.Sleep(exp);

            for (uint i = 0; i < timeoutSeconds; i++)
            {
                lock (m_sync)
                {
                    if (AppState == "Looping")
                        return;
                }

                System.Threading.Thread.Sleep(1000);
                CheckConnected();
            }

            throw new GuiderException("timed-out waiting for guiding to start looping");
        }

        // get the guider pixel scale in arc-seconds per pixel
        public override double PixelScale()
        {
            JObject res = Call("get_pixel_scale");
            return (double) res["result"];
        }

        // get a list of the Equipment Profile names
        public override List<string> GetEquipmentProfiles()
        {
            JObject res = Call("get_profiles");

            List<string> profiles = new List<string>();

            JArray ary = (JArray) res["result"];
            foreach (var p in ary)
            {
                string name = (string) p["name"];
                profiles.Add(name);
            }

            return profiles;
        }

        static JToken GetDefault(JToken obj, string name, JToken dflt)
        {
            return ((JObject) obj).ContainsKey(name) ? obj[name] : dflt;
        }

        static uint DEFAULT_STOPCAPTURE_TIMEOUT = 10;

        // connect the equipment in an equipment profile
        public override void ConnectEquipment(string profileName)
        {
            JObject res = Call("get_profile");

            JObject prof = (JObject) res["result"];

            string profname = profileName;

            if ((string) prof["name"] != profname)
            {
                res = Call("get_profiles");
                JArray profiles = (JArray)res["result"];
                int profid = -1;
                foreach (var p in profiles)
                {
                    string name = (string) p["name"];
                    Debug.WriteLine(String.Format("found profile {0}", name));
                    if (name == profname)
                    {
                        profid = (int) GetDefault(p, "id", new JValue(-1));
                        Debug.WriteLine(String.Format("found profid {0}", profid));
                        break;
                    }
                }
                if (profid == -1)
                    throw new GuiderException("invalid phd2 profile name: " + profname);

                StopCapture(DEFAULT_STOPCAPTURE_TIMEOUT);

                Call("set_connected", new JValue(false));
                Call("set_profile", new JValue(profid));
            }

            Call("set_connected", new JValue(true));
        }

        // disconnect equipment
        public override void DisconnectEquipment()
        {
            StopCapture(DEFAULT_STOPCAPTURE_TIMEOUT);
            Call("set_connected", new JValue(false));
        }

        // get the AppState (https://github.com/OpenPHDGuiding/phd2/wiki/EventMonitoring#appstate)
        // and current guide error
        public override void GetStatus(out string appState, out double avgDist)
        {
            CheckConnected();

            lock (m_sync)
            {
                appState = AppState;
                avgDist = AvgDist;
            }
        }

        // check if currently guiding
        public override bool IsGuiding()
        {
            string st;
            double dist;
            GetStatus(out st, out dist);
            return is_guiding(st);
        }

        // pause guiding (looping exposures continues)
        public override void Pause()
        {
            Call("set_paused", new JValue(true));
        }

        // un-pause guiding
        public override void Unpause()
        {
            Call("set_paused", new JValue(false));
        }

        // save the current guide camera frame (FITS format), returning the name of the file.
        // The caller will need to remove the file when done.
        public override string SaveImage()
        {
            JObject res = Call("save_image");
            return (string) res["result"]["filename"];
        }
    }
}
