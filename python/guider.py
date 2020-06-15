import copy
import json
import math
import selectors
import socket
import threading
import time

class SettleProgress:
    """Info related to progress of settling after guiding starts or after
    a dither

    """
    def __init__(self):
        self.Done = False
        self.Distance = 0.0
        self.SettlePx = 0.0
        self.Time = 0.0
        self.SettleTime = 0.0
        self.Status = 0
        self.Error = ''

class GuideStats:
    """cumulative guide stats since guiding started and settling
    completed

    """
    def __init__(self):
        self.rms_tot = 0.0
        self.rms_ra = 0.0
        self.rms_dec = 0.0
        self.peak_ra = 0.0
        self.peak_dec = 0.0

class GuiderException(Exception):
    """GuiderException is the base class for any excettions raied by the
    Guider methods

    """
    pass

class _Accum:
    def __init__(self):
        self.Reset()
    def Reset(self):
        self.n = 0
        self.a = self.q = self.peak = 0
    def Add(self, x):
        ax = abs(x)
        if ax > self.peak:
            self.peak = ax
        self.n += 1
        d = x - self.a
        self.a += d / self.n
        self.q += (x - self.a) * d
    def Mean(self):
        return self.a
    def Stdev(self):
        return math.sqrt(self.q / self.n) if self.n >= 1 else 0.0
    def Peak(self):
        return self.peak

class _Conn:
    def __init__(self):
        self.lines = []
        self.buf = b''
        self.sock = None
        self.sel = None
        self.terminate = False

    def __del__(self):
        self.Disconnect()

    def Connect(self, hostname, port):
        self.sock = socket.socket()
        try:
            self.sock.connect((hostname, port))
            self.sock.setblocking(False)  # non-blocking
            self.sel = selectors.DefaultSelector()
            self.sel.register(self.sock, selectors.EVENT_READ)
        except Exception:
            self.sel = None
            self.sock = None
            raise

    def Disconnect(self):
        if self.sel is not None:
            self.sel.unregister(self.sock)
            self.sel = None
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def IsConnected(self):
        return self.sock is not None

    def ReadLine(self):
        #print(f"DBG: ReadLine enter lines:{len(self.lines)}")
        while not self.lines:
            #print("DBG: begin wait")
            while True:
                if self.terminate:
                    return ''
                events = self.sel.select(0.5)
                if events:
                    break
            #print("DBG: call recv")
            s = self.sock.recv(4096)
            #print(f"DBG: recvd: {len(s)}: {s}")
            i0 = 0
            i = i0
            while i < len(s):
                if s[i] == b'\r'[0] or s[i] == b'\n'[0]:
                    self.buf += s[i0 : i]
                    if self.buf:
                        self.lines.append(self.buf)
                        self.buf = b''
                    i += 1
                    i0 = i
                else:
                    i += 1
            self.buf += s[i0 : i]
        return self.lines.pop(0)

    def WriteLine(self, s):
        b = s.encode()
        totsent = 0
        while totsent < len(b):
            sent = self.sock.send(b[totsent:])
            if sent == 0:
                raise RuntimeError("socket connection broken")
            totsent += sent

    def Terminate(self):
        self.terminate = True

class Guider:
    """The main class for interacting with PHD2"""

    DEFAULT_STOPCAPTURE_TIMEOUT = 10

    def __init__(self, hostname = "localhost", instance = 1):
        self.hostname = hostname
        self.instance = instance
        self.conn = None
        self.terminate = False
        self.worker = None
        self.lock = threading.Lock()
        self.cond = threading.Condition()
        self.response = None
        self.AppState = ''
        self.AvgDist = 0
        self.Version = ''
        self.PHDSubver = ''
        self.accum_active = False
        self.settle_px = 0
        self.accum_ra = _Accum()
        self.accum_dec = _Accum()
        self.Stats = GuideStats()
        self.Settle = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.Disconnect()

    @staticmethod
    def _is_guiding(st):
        return st == "Guiding" or st == "LostLock"

    @staticmethod
    def _accum_get_stats(ra, dec):
        stats = GuideStats()
        stats.rms_ra = ra.Stdev()
        stats.rms_dec = dec.Stdev()
        stats.peak_ra = ra.Peak()
        stats.peak_dec = dec.Peak()
        return stats

    def _handle_event(self, ev):
        e = ev["Event"]
        if e == "AppState":
            with self.lock:
                self.AppState = ev["State"]
                if self._is_guiding(self.AppState):
                    self.AvgDist = 0  # until we get a GuideStep event
        elif e == "Version":
            with self.lock:
                self.Version = ev["PHDVersion"]
                self.PHDSubver = ev["PHDSubver"]
        elif e == "StartGuiding":
            self.accum_active = True
            self.accum_ra.Reset()
            self.accum_dec.Reset()
            stats = self._accum_get_stats(self.accum_ra, self.accum_dec)
            with self.lock:
                self.Stats = stats
        elif e == "GuideStep":
            if self.accum_active:
                self.accum_ra.Add(ev["RADistanceRaw"])
                self.accum_dec.Add(ev["DECDistanceRaw"])
                stats = self._accum_get_stats(self.accum_ra, self.accum_dec)
            with self.lock:
                self.AppState = "Guiding"
                self.AvgDist = ev["AvgDist"]
                if self.accum_active:
                    self.Stats = stats
        elif e == "SettleBegin":
            self.accum_active = False  # exclude GuideStep messages from stats while settling
        elif e == "Settling":
            s = SettleProgress()
            s.Done = False
            s.Distance = ev["Distance"]
            s.SettlePx = self.settle_px
            s.Time = ev["Time"]
            s.SettleTime = ev["SettleTime"]
            s.Status = 0
            with self.lock:
                self.Settle = s
        elif e == "SettleDone":
            self.accum_active = True
            self.accum_ra.Reset()
            self.accum_dec.Reset()
            stats = self._accum_get_stats(self.accum_ra, self.accum_dec)
            s = SettleProgress()
            s.Done = True
            s.Status = ev["Status"]
            s.Error = ev.get("Error")
            with self.lock:
                self.Settle = s
                self.Stats = stats
        elif e == "Paused":
            with self.lock:
                self.AppState = "Paused"
        elif e == "StartCalibration":
            with self.lock:
                self.AppState = "Calibrating"
        elif e == "LoopingExposures":
            with self.lock:
                self.AppState = "Looping"
        elif e == "LoopingExposuresStopped" or e == "GuidingStopped":
            with self.lock:
                self.AppState = "Stopped"
        elif e == "StarLost":
            with self.lock:
                self.AppState = "LostLock"
                self.AvgDist = ev["AvgDist"]
        else:
            #print(f"DBG: todo: handle event {e}")
            pass
        
    def _worker(self):
        while not self.terminate:
            line = self.conn.ReadLine()
            #print(f"DBG: L: {line}")
            if not line:
                if not self.terminate:
                    # server disconnected
                    #print("DBG: server disconnected")
                    pass
                break
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                # ignore invalid json
                #print("DBG: ignoring invalid json response")
                continue
            if "jsonrpc" in j:
                # a response
                #print(f"DBG: R: {line}\n")
                with self.cond:
                    self.response = j
                    self.cond.notify()
            else:
                self._handle_event(j)

    def Connect(self):
        """connect to PHD2 -- call Connect before calling any of the server API methods below"""
        self.Disconnect()
        try:
            self.conn = _Conn()
            self.conn.Connect(self.hostname, 4400 + self.instance - 1)
            self.terminate = False
            self.worker = threading.Thread(target=self._worker)
            self.worker.start()
            #print("DBG: connect done")
        except Exception:
            self.Disconnect()
            raise

    def Disconnect(self):
        """disconnect from PHD2"""
        if self.worker is not None:
            if self.worker.is_alive():
                #print("DBG: terminating worker")
                self.terminate = True
                self.conn.Terminate()
                #print("DBG: joining worker")
                self.worker.join()
            self.worker = None
        if self.conn is not None:
            self.conn.Disconnect()
            self.conn = None
        #print("DBG: disconnect done")

    @staticmethod
    def _make_jsonrpc(method, params):
        req = {
            "method": method,
            "id": 1
        }
        if params is not None:
            if isinstance(params, (list, dict)):
                req["params"] = params
            else:
                # single non-null parameter
                req["params"] = [ params ]
        return json.dumps(req,separators=(',', ':'))

    @staticmethod
    def _failed(res):
        return "error" in res

    def Call(self, method, params = None):
        """this function can be used for raw JSONRPC method
        invocation. Generally you won't need to use this as it is much
        more convenient to use the higher-level methods below

        """
        s = self._make_jsonrpc(method, params)
        #print(f"DBG: Call: {s}")
        # send request
        self.conn.WriteLine(s + "\r\n")
        # wait for response
        with self.cond:
            while not self.response:
                self.cond.wait()
            response = self.response
            self.response = None
        if self._failed(response):
            raise GuiderException(response["error"]["message"])
        return response

    def _CheckConnected(self):
        if not self.conn.IsConnected():
            raise GuiderException("PHD2 Server disconnected")

    def Guide(self, settlePixels, settleTime, settleTimeout):
        """Start guiding with the given settling parameters. PHD2 takes care
        of looping exposures, guide star selection, and settling. Call
        CheckSettling() periodically to see when settling is complete.

        """
        self._CheckConnected()
        s = SettleProgress()
        s.Done = False
        s.Distance = 0
        s.SettlePx = settlePixels
        s.Time = 0
        s.SettleTime = settleTime
        s.Status = 0
        with self.lock:
            if self.Settle and not self.Settle.Done:
                raise GuiderException("cannot guide while settling")
            self.Settle = s
        try:
            self.Call(
                "guide",
                [
                    {
                        "pixels" : settlePixels,
                        "time": settleTime,
                        "timeout": settleTimeout,
                    },
                    False, # don't force calibration
                ]
            )
            self.settle_px = settlePixels
        except Exception:
            with self.lock:
                self.Settle = None
            raise

    def Dither(self, ditherPixels, settlePixels, settleTime, settleTimeout):
        """Dither guiding with the given dither amount and settling parameters. Call CheckSettling()
        periodically to see when settling is complete.
        """
        self._CheckConnected()
        s = SettleProgress()
        s.Done = False
        s.Distance = ditherPixels
        s.SettlePx = settlePixels
        s.Time = 0
        s.SettleTime = settleTime
        s.Status = 0
        with self.lock:
            if self.Settle and not self.Settle.Done:
                raise GuiderException("cannot dither while settling")
            self.Settle = s
        try:
            self.Call(
                "dither",
                [
                    ditherPixels,
                    False,
                    {
                        "pixels" : settlePixels,
                        "time": settleTime,
                        "timeout": settleTimeout,
                    },
                ]
            )
            self.settle_px = settlePixels
        except Exception:
            with self.lock:
                self.Settle = None
            raise

    def IsSettling(self):
        """Check if phd2 is currently in the process of settling after a Guide
        or Dither"""
        self._CheckConnected()
        with self.lock:
            if self.Settle:
                return True
        # for app init, initialize the settle state to a consistent
        # value as if Guide had been called
        res = self.Call("get_settling")
        val = res["result"]
        if val:
            s = SettleProgress()
            s.Done = False
            s.Distance = -1.0
            s.SettlePx = 0.0
            s.Time = 0.0
            s.SettleTime = 0.0
            s.Status = 0
            with self.lock:
                if self.Settle is None:
                    self.Settle = s
        return val

    def CheckSettling(self):
        """Get the progress of settling"""
        self._CheckConnected()
        ret = SettleProgress()
        with self.lock:
            if not self.Settle:
                raise GuiderException("not settling")
            if self.Settle.Done:
                # settle is done
                ret.Done = True
                ret.Status = self.Settle.Status
                ret.Error = self.Settle.Error
                self.Settle = None
            else:
                # settle in progress
                ret.Done = False
                ret.Distance = self.Settle.Distance
                ret.SettlePx = self.settle_px
                ret.Time = self.Settle.Time
                ret.SettleTime = self.Settle.SettleTime
        return ret

    def GetStats(self):
        """Get the guider statistics since guiding started. Frames captured
        while settling is in progress are excluded from the stats.

        """
        self._CheckConnected()
        with self.lock:
            stats = copy.copy(self.Stats)
        stats.rms_tot = math.hypot(stats.rms_ra, stats.rms_dec)
        return stats

    def StopCapture(self, timeoutSeconds = 10):
        """stop looping and guiding"""
        self.Call("stop_capture")
        for i in range(0, timeoutSeconds):
            with self.lock:
                if self.AppState == "Stopped":
                    return
            time.sleep(1)
            self._CheckConnected()
        # hack! workaround bug where PHD2 sends a GuideStep after stop
        # request and fails to send GuidingStopped
        res = self.Call("get_app_state")
        st = res["result"]
        with self.lock:
            self.AppState = st
        if st == "Stopped":
            return
        # end workaround
        raise GuiderException(f"guider did not stop capture after {timeoutSeconds} seconds!")

    def Loop(self, timeoutSeconds = 10):
        """start looping exposures"""
        self._CheckConnected()
        # already looping?
        with self.lock:
            if self.AppState == "Looping":
                return
        res = self.Call("get_exposure")
        exp = res["result"]
        self.Call("loop")
        time.sleep(exp)
        for i in range(0, timeoutSeconds):
            with self.lock:
                if self.AppState == "Looping":
                    return
            time.sleep(1)
            self._CheckConnected()
        raise GuiderException("timed-out waiting for guiding to start looping")

    def PixelScale(self):
        """get the guider pixel scale in arc-seconds per pixel"""
        res = self.Call("get_pixel_scale")
        return res["result"]

    def GetEquipmentProfiles(self):
        """get a list of the Equipment Profile names"""
        res = self.Call("get_profiles")
        profiles = []
        for p in res["result"]:
            profiles.append(p["name"])
        return profiles

    def ConnectEquipment(self, profileName):
        """connect the equipment in an equipment profile"""
        res = self.Call("get_profile")
        prof = res["result"]
        if prof["name"] != profileName:
            res = self.Call("get_profiles")
            profiles = res["result"]
            profid = -1
            for p in profiles:
                name = p["name"]
                if name == profileName:
                    profid = p.get("id", -1)
                    break
            if profid == -1:
                raise GuiderException(f"invalid phd2 profile name: {profileName}")
            self.StopCapture(self.DEFAULT_STOPCAPTURE_TIMEOUT)
            self.Call("set_connected", False)
            self.Call("set_profile", profid)
        self.Call("set_connected", True)

    def DisconnectEquipment(self):
        """disconnect equipment"""
        self.StopCapture(self.DEFAULT_STOPCAPTURE_TIMEOUT)
        self.Call("set_connected", False)

    def GetStatus(self):
        """get the AppState
        (https://github.com/OpenPHDGuiding/phd2/wiki/EventMonitoring#appstate)
        and current guide error

        """
        self._CheckConnected()
        with self.lock:
            return self.AppState, self.AvgDist

    def IsGuiding(self):
        """check if currently guiding"""
        st, dist = self.GetStatus()
        return self._is_guiding(st)

    def Pause(self):
        """pause guiding (looping exposures continues)"""
        self.Call("set_paused", True)

    def Unpause(self):
        """un-pause guiding"""
        self.Call("set_paused", False)

    def SaveImage(self, filename):
        """save the current guide camera frame (FITS format), returning the
        name of the file in *filename.  The caller will need to remove
        the file when done.

        """
        res = self.Call("save_image")
        return res["result"]["filename"]
