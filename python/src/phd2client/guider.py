import copy
import dataclasses
import json
import math
import selectors
import socket
import threading
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any, ClassVar, Self


@dataclass
class SettleProgress:
    """
    Info related to progress of settling after guiding starts or after a dither
    """

    Done: bool = False
    Distance: float = 0
    SettlePx: float = 0
    Time: float = 0
    SettleTime: float = 0
    Status: int = 0
    Error: str | None = None


@dataclass
class GuideStats:
    """
    Cumulative guide stats since guiding started and settling completed
    """

    rms_tot: float = 0
    rms_ra: float = 0
    rms_dec: float = 0
    peak_ra: float = 0
    peak_dec: float = 0


class GuiderError(Exception):
    """
    GuiderError is the base class for any exceptions raised by the Guider methods
    """

    pass


class NotConnectedError(GuiderError):
    def __init__(self) -> None:
        super().__init__("not connected")


@dataclass(init=False)
class _Accum:
    n: int
    a: float
    q: float
    peak: float

    def __init__(self):
        self.Reset()

    def Reset(self):
        self.n = 0
        self.a = self.q = self.peak = 0

    def Add(self, x: float):
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


@dataclass
class _Conn:
    lines: list[bytes] = dataclasses.field(default_factory=list[bytes])
    buf: bytes = b""
    sock: socket.socket | None = None
    sel: Any | None = None
    terminate: bool = False

    def __del__(self):
        self.close()

    def Connect(self, hostname: str, port: int):
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

    def close(self):
        if self.sel is not None:
            if self.sock:
                self.sel.unregister(self.sock)
            self.sel = None
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def IsConnected(self):
        return self.sock is not None

    def ReadLine(self):
        assert self.sock is not None
        assert self.sel is not None
        # print(f"DBG: ReadLine enter lines:{len(self.lines)}")
        while not self.lines:
            # print("DBG: begin wait")
            while True:
                if self.terminate:
                    return ""
                events = self.sel.select(0.5)
                if events:
                    break
            # print("DBG: call recv")
            s = self.sock.recv(4096)
            # print(f"DBG: recvd: {len(s)}: {s}")
            i0 = 0
            i = i0
            while i < len(s):
                if s[i] == b"\r"[0] or s[i] == b"\n"[0]:
                    self.buf += s[i0:i]
                    if self.buf:
                        self.lines.append(self.buf)
                        self.buf = b""
                    i += 1
                    i0 = i
                else:
                    i += 1
            self.buf += s[i0:i]
        return self.lines.pop(0)

    def WriteLine(self, s: str):
        assert self.sock is not None
        b = s.encode()
        totsent = 0
        while totsent < len(b):
            sent = self.sock.send(b[totsent:])
            if sent == 0:
                raise RuntimeError("socket connection broken")
            totsent += sent

    def Terminate(self):
        self.terminate = True


@dataclass
class Subframe:
    x: int
    y: int
    width: int
    height: int


@dataclass
class SingleFrameResult:
    success: bool
    error_message: str | None
    path: str | None


@dataclass(init=False)
class Guider:
    """The main class for interacting with PHD2"""

    DEFAULT_STOPCAPTURE_TIMEOUT: ClassVar[float] = 10

    hostname: str
    instance: int
    conn: _Conn | None = None
    terminate: bool = False
    worker: threading.Thread | None = None
    lock = threading.Lock()
    cond = threading.Condition()
    response: dict[str, Any] | None = None
    AppState: str = ""
    AvgDist: float = 0
    Version: str = ""
    PHDSubver: str = ""
    accum_active: bool = False
    settle_px: float = 0
    accum_ra = _Accum()
    accum_dec = _Accum()
    Stats = GuideStats()
    Settle: SettleProgress | None = None
    single_frame: SingleFrameResult | None = None

    def __init__(
        self, hostname: str = "localhost", instance: int = 1, connect: bool = False
    ):
        self.hostname = hostname
        self.instance = instance
        if connect:
            self.Connect()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> bool | None:
        self.Disconnect()

    @staticmethod
    def _is_guiding(st: str):
        return st == "Guiding" or st == "LostLock"

    @staticmethod
    def _accum_get_stats(ra: _Accum, dec: _Accum):
        stats = GuideStats()
        stats.rms_ra = ra.Stdev()
        stats.rms_dec = dec.Stdev()
        stats.peak_ra = ra.Peak()
        stats.peak_dec = dec.Peak()
        return stats

    def _handle_event(self, ev: dict[str, Any]):
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
                    self.Stats = stats  # type: ignore
        elif e == "SettleBegin":
            self.accum_active = (
                False  # exclude GuideStep messages from stats while settling
            )
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
        elif e == "SingleFrameComplete":
            result = SingleFrameResult(
                success=ev["Success"],
                error_message=ev.get("Error"),
                path=ev.get("Path"),
            )
            with self.lock:
                self.single_frame = result
        else:
            # print(f"DBG: todo: handle event {e}")
            pass

    def _worker(self):
        assert self.conn is not None
        while not self.terminate:
            line = self.conn.ReadLine()
            # print(f"DBG: L: {line}")
            if not line:
                if not self.terminate:
                    # server disconnected
                    # print("DBG: server disconnected")
                    pass
                break
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                # ignore invalid json
                # print("DBG: ignoring invalid json response")
                continue
            if "jsonrpc" in j:
                # a response
                # print(f"DBG: R: {line}\n")
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
            # print("DBG: connect done")
        except Exception:
            self.Disconnect()
            raise

    def Disconnect(self):
        """disconnect from PHD2"""
        if self.worker is not None:
            if self.worker.is_alive():
                # print("DBG: terminating worker")
                self.terminate = True
                if self.conn is not None:
                    self.conn.Terminate()
                # print("DBG: joining worker")
                self.worker.join()
            self.worker = None
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        # print("DBG: disconnect done")

    @staticmethod
    def _make_jsonrpc(method: str, params: Any):
        req: dict[str, Any] = {"method": method, "id": 1}
        if params is not None:
            if isinstance(params, (list, dict)):
                req["params"] = params
            else:
                # single non-null parameter
                req["params"] = [params]
        return json.dumps(req, separators=(",", ":"))

    @staticmethod
    def _failed(res: dict[str, Any]):
        return "error" in res

    def Call(self, method: str, params: Any = None):
        """this function can be used for raw JSONRPC method
        invocation. Generally you won't need to use this as it is much
        more convenient to use the higher-level methods below

        """
        if self.conn is None:
            raise NotConnectedError
        s = self._make_jsonrpc(method, params)
        # print(f"DBG: Call: {s}")
        # send request
        self.conn.WriteLine(s + "\r\n")
        # wait for response
        with self.cond:
            while not self.response:
                self.cond.wait()
            response = self.response
            self.response = None
        if self._failed(response):
            raise GuiderError(response["error"]["message"])
        return response

    def _CheckConnected(self):
        if not self.conn:
            raise NotConnectedError
        if not self.conn.IsConnected():
            raise GuiderError("PHD2 Server disconnected")

    def Guide(self, settlePixels: float, settleTime: float, settleTimeout: float):
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
                raise GuiderError("cannot guide while settling")
            self.Settle = s
        try:
            self.Call(
                "guide",
                [
                    {
                        "pixels": settlePixels,
                        "time": settleTime,
                        "timeout": settleTimeout,
                    },
                    False,  # don't force calibration
                ],
            )
            self.settle_px = settlePixels
        except Exception:
            with self.lock:
                self.Settle = None
            raise

    def Dither(
        self,
        ditherPixels: float,
        settlePixels: float,
        settleTime: float,
        settleTimeout: float,
    ):
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
                raise GuiderError("cannot dither while settling")
            self.Settle = s
        try:
            self.Call(
                "dither",
                [
                    ditherPixels,
                    False,
                    {
                        "pixels": settlePixels,
                        "time": settleTime,
                        "timeout": settleTimeout,
                    },
                ],
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
                raise GuiderError("not settling")
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

    def StopCapture(self, timeoutSeconds: float = 10):
        """stop looping and guiding"""
        self.Call("stop_capture")
        deadline = time.monotonic() + timeoutSeconds
        while True:
            with self.lock:
                if self.AppState == "Stopped":
                    return
            time.sleep(1)
            self._CheckConnected()
            if time.monotonic() > deadline:
                break
        # hack! workaround bug where PHD2 sends a GuideStep after stop
        # request and fails to send GuidingStopped
        res = self.Call("get_app_state")
        st = res["result"]
        with self.lock:
            self.AppState = st
        if st == "Stopped":
            return
        # end workaround
        raise GuiderError(
            f"guider did not stop capture after {timeoutSeconds} seconds!"
        )

    def Loop(self, timeoutSeconds: float = 10):
        """start looping exposures"""
        self._CheckConnected()
        # already looping?
        with self.lock:
            if self.AppState == "Looping":
                return
        res = self.Call("get_exposure")
        exp_ms = res["result"]
        self.Call("loop")
        deadline = time.monotonic() + timeoutSeconds
        time.sleep(exp_ms / 1000)
        while True:
            with self.lock:
                if self.AppState == "Looping":
                    return
            time.sleep(1)
            self._CheckConnected()
            if time.monotonic() > deadline:
                break
        raise GuiderError("timed-out waiting for guiding to start looping")

    def PixelScale(self):
        """get the guider pixel scale in arc-seconds per pixel"""
        res = self.Call("get_pixel_scale")
        return res["result"]

    def GetExposure(self) -> int:
        """get the current exposure duration in milliseconds"""
        res = self.Call("get_exposure")
        return res["result"]

    def GetEquipmentProfiles(self):
        """get a list of the Equipment Profile names"""
        res = self.Call("get_profiles")
        profiles: list[str] = []
        for p in res["result"]:
            profiles.append(p["name"])
        return profiles

    def ConnectEquipment(self, profileName: str):
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
                raise GuiderError(f"invalid phd2 profile name: {profileName}")
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
        st, _ = self.GetStatus()
        return self._is_guiding(st)

    def Pause(self):
        """pause guiding (looping exposures continues)"""
        self.Call("set_paused", True)

    def Unpause(self):
        """un-pause guiding"""
        self.Call("set_paused", False)

    def SaveImage(self):
        """
        Save the current guide camera frame (FITS format), returning the name of the
        file.  The caller will need to remove the file when done.
        """
        res = self.Call("save_image")
        return res["result"]["filename"]

    def Shutdown(self):
        """
        Terminate PHD2
        """
        self.Call("shutdown")

    def CaptureSingleFrame(
        self,
        *,
        exposure: int | None = None,
        binning: int | None = None,
        gain: int | None = None,
        roi: Subframe | None = None,
        path: str | None = None,
        save: bool | None = None,
    ):
        if path is not None and save is False:
            raise ValueError(
                "invalid arguments: when save is False, the path argument should be omitted"
            )
        params: dict[str, Any] = {}
        if exposure is not None:
            params["exposure"] = exposure
        if binning is not None:
            params["binning"] = binning
        if gain is not None:
            params["gain"] = gain
        if roi is not None:
            params["subframe"] = [roi.x, roi.y, roi.width, roi.height]
        if path is not None:
            params["path"] = path
        if save is not None:
            params["save"] = save
        with self.lock:
            self.single_frame = None
        self.Call("capture_single_frame", params)

    def CheckSingleFrame(self) -> SingleFrameResult | None:
        with self.lock:
            result = self.single_frame
            self.single_frame = None
        return result
