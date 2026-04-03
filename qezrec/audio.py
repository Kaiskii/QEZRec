import ctypes
import ctypes.wintypes
import logging
import threading
import time
import wave
from ctypes import HRESULT, POINTER, byref, c_uint32, c_void_p

from comtypes import GUID

log = logging.getLogger(__name__)

# COM GUIDs
IID_IUnknown = GUID("{00000000-0000-0000-C000-000000000046}")
IID_IAudioClient = GUID("{1CB9AD4C-DBFA-4c32-B178-C2F568A703B2}")
IID_IAudioCaptureClient = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
IID_CompletionHandler = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
IID_IAgileObject = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")

VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"

# Wave format tags
WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_IEEE_FLOAT = 0x0003
WAVE_FORMAT_EXTENSIBLE = 0xFFFE

# Flags
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_BUFFERFLAGS_SILENT = 0x2


# Structures
class PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
    _fields_ = [
        ("TargetProcessId", ctypes.wintypes.DWORD),
        ("ProcessLoopbackMode", ctypes.c_int),
    ]


class ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [
        ("ActivationType", ctypes.c_int),
        ("ProcessLoopbackParams", PROCESS_LOOPBACK_PARAMS),
    ]


class BLOB(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("pBlobData", ctypes.c_void_p),
    ]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("blob", BLOB),
    ]


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", ctypes.c_ushort),
        ("nChannels", ctypes.c_ushort),
        ("nSamplesPerSec", ctypes.c_uint),
        ("nAvgBytesPerSec", ctypes.c_uint),
        ("nBlockAlign", ctypes.c_ushort),
        ("wBitsPerSample", ctypes.c_ushort),
        ("cbSize", ctypes.c_ushort),
    ]


# Raw COM Completion Handler
class _CompletionHandler:
    """Raw COM implementation of IActivateAudioInterfaceCompletionHandler + IAgileObject."""

    def __init__(self):
        self.event = threading.Event()
        self.op_ptr = None
        self._refs = 1
        self._lock = threading.Lock()
        # prevent GC of closures
        self._qi_fn = ctypes.CFUNCTYPE(HRESULT, c_void_p, POINTER(GUID), POINTER(c_void_p))(self._qi)
        self._ar_fn = ctypes.CFUNCTYPE(ctypes.c_ulong, c_void_p)(self._ar)
        self._re_fn = ctypes.CFUNCTYPE(ctypes.c_ulong, c_void_p)(self._re)
        self._ac_fn = ctypes.CFUNCTYPE(HRESULT, c_void_p, c_void_p)(self._ac)
        self._vtbl = (c_void_p * 4)(
            ctypes.cast(self._qi_fn, c_void_p),
            ctypes.cast(self._ar_fn, c_void_p),
            ctypes.cast(self._re_fn, c_void_p),
            ctypes.cast(self._ac_fn, c_void_p),
        )
        self._vtbl_p = ctypes.cast(ctypes.pointer(self._vtbl), c_void_p)
        self._obj = ctypes.pointer(self._vtbl_p)

    def _qi(self, this, riid, ppv):
        iid = riid.contents
        if iid in (IID_IUnknown, IID_CompletionHandler, IID_IAgileObject):
            ppv[0] = ctypes.cast(self._obj, c_void_p)
            with self._lock:
                self._refs += 1
            return 0
        ppv[0] = c_void_p(0)
        return -2147467262  # E_NOINTERFACE

    def _ar(self, this):
        with self._lock:
            self._refs += 1
            return self._refs

    def _re(self, this):
        with self._lock:
            self._refs -= 1
            return self._refs

    def _ac(self, this, op):
        self.op_ptr = op
        self.event.set()
        return 0

    @property
    def com_ptr(self):
        return ctypes.cast(self._obj, c_void_p)


# Vtable helpers
def _vtbl_method(ptr, index, restype, *argtypes):
    """Get a function from a COM vtable by index. Always use c_long for HRESULT to avoid auto-raise."""
    vtbl = ctypes.cast(ctypes.cast(ptr, POINTER(c_void_p))[0], POINTER(c_void_p * (index + 1))).contents
    # Use c_long instead of HRESULT to prevent ctypes from auto-raising on failure
    actual_restype = ctypes.c_long if restype is HRESULT else restype
    return ctypes.CFUNCTYPE(actual_restype, c_void_p, *argtypes)(vtbl[index])


def _activate_for_process(pid: int) -> c_void_p:
    """Activate an IAudioClient for process loopback capture. Returns raw COM pointer."""
    params = ACTIVATION_PARAMS()
    params.ActivationType = 1  # PROCESS_LOOPBACK
    params.ProcessLoopbackParams.TargetProcessId = pid
    params.ProcessLoopbackParams.ProcessLoopbackMode = 0  # INCLUDE_TARGET_PROCESS_TREE

    prop = PROPVARIANT()
    prop.vt = 65  # VT_BLOB
    prop.blob.cbSize = ctypes.sizeof(params)
    prop.blob.pBlobData = ctypes.cast(ctypes.pointer(params), ctypes.c_void_p)

    handler = _CompletionHandler()
    op_out = c_void_p()

    func = ctypes.windll.mmdevapi.ActivateAudioInterfaceAsync
    func.restype = HRESULT
    func.argtypes = [ctypes.c_wchar_p, POINTER(GUID), POINTER(PROPVARIANT), c_void_p, POINTER(c_void_p)]

    hr = func(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, byref(IID_IAudioClient), byref(prop),
              handler.com_ptr, byref(op_out))
    if hr != 0:
        raise OSError(f"ActivateAudioInterfaceAsync: 0x{hr & 0xFFFFFFFF:08X}")

    if not handler.event.wait(timeout=5):
        raise TimeoutError("Audio activation timed out")

    # IActivateAudioInterfaceAsyncOperation::GetActivateResult is at vtable index 3
    GetActivateResult = _vtbl_method(handler.op_ptr, 3, HRESULT, POINTER(HRESULT), POINTER(c_void_p))
    act_hr = HRESULT()
    client_ptr = c_void_p()
    GetActivateResult(handler.op_ptr, byref(act_hr), byref(client_ptr))

    if act_hr.value != 0:
        raise OSError(f"Activation result: 0x{act_hr.value & 0xFFFFFFFF:08X}")

    return client_ptr


# AudioCapture
class AudioCapture:
    """Captures audio from a specific process using WASAPI Process Loopback,
    or falls back to system-wide loopback via pyaudiowpatch.
    """

    def __init__(self):
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, output_path: str, pid: int | None = None):
        self._output_path = output_path
        self._pid = pid
        self._running.set()
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()

    def _record_loop(self):
        if self._pid:
            try:
                self._record_process(self._pid)
                return
            except Exception as e:
                log.warning(f"Process audio failed ({e}), falling back to system loopback")
                import traceback
                log.debug(traceback.format_exc())
        self._record_system()

    def _record_process(self, pid: int):
        """Capture audio from a specific process via WASAPI process loopback."""
        import struct

        log.info(f"[AUDIO] Activating process loopback for PID {pid}...")
        client_ptr = _activate_for_process(pid)
        log.info(f"[AUDIO] Got IAudioClient: {client_ptr.value:#x}")

        # IAudioClient vtable indices: https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nn-audioclient-iaudioclient
        Initialize  = _vtbl_method(client_ptr, 3,  HRESULT, c_uint32, c_uint32, ctypes.c_int64, ctypes.c_int64, POINTER(WAVEFORMATEX), POINTER(GUID))
        GetBufferSize = _vtbl_method(client_ptr, 4,  HRESULT, POINTER(c_uint32))
        Start         = _vtbl_method(client_ptr, 10, HRESULT)
        Stop          = _vtbl_method(client_ptr, 11, HRESULT)
        GetService    = _vtbl_method(client_ptr, 14, HRESULT, POINTER(GUID), POINTER(c_void_p))

        # Process loopback doesn't support GetMixFormat - use standard WASAPI shared format
        # (32-bit float is the standard format for Windows audio engine)
        sample_rate = 48000
        channels = 2
        bits = 32
        is_float = True
        block_align = channels * (bits // 8)  # 8 bytes per frame

        fmt = WAVEFORMATEX()
        fmt.wFormatTag = WAVE_FORMAT_IEEE_FLOAT
        fmt.nChannels = channels
        fmt.nSamplesPerSec = sample_rate
        fmt.wBitsPerSample = bits
        fmt.nBlockAlign = block_align
        fmt.nAvgBytesPerSec = sample_rate * block_align
        fmt.cbSize = 0

        log.info(f"[AUDIO] Format: {sample_rate}Hz, {channels}ch, {bits}bit float")
        log.info("[AUDIO] Initializing IAudioClient (shared mode, LOOPBACK flag)...")
        hr = Initialize(client_ptr, 0, AUDCLNT_STREAMFLAGS_LOOPBACK, 200_000, 0, byref(fmt), None)
        if hr != 0:
            raise OSError(f"IAudioClient::Initialize: 0x{hr & 0xFFFFFFFF:08X}")
        log.info("[AUDIO] IAudioClient initialized OK")

        buf_size = c_uint32()
        GetBufferSize(client_ptr, byref(buf_size))
        log.info(f"[AUDIO] Buffer size: {buf_size.value} frames")

        cap_ptr = c_void_p()
        hr = GetService(client_ptr, byref(IID_IAudioCaptureClient), byref(cap_ptr))
        if hr != 0:
            raise OSError(f"GetService(CaptureClient): 0x{hr & 0xFFFFFFFF:08X}")
        log.info(f"[AUDIO] Got IAudioCaptureClient: {cap_ptr.value:#x}")

        GetBuffer = _vtbl_method(cap_ptr, 3, HRESULT,
                                 POINTER(c_void_p), POINTER(c_uint32),
                                 POINTER(ctypes.wintypes.DWORD),
                                 POINTER(ctypes.c_uint64), POINTER(ctypes.c_uint64))
        ReleaseBuffer = _vtbl_method(cap_ptr, 4, HRESULT, c_uint32)
        GetNextPacketSize = _vtbl_method(cap_ptr, 5, HRESULT, POINTER(c_uint32))

        log.info(f"[AUDIO] Starting capture: PID {pid} @ {sample_rate}Hz, {channels}ch, {bits}bit")
        hr = Start(client_ptr)
        if hr != 0:
            raise OSError(f"IAudioClient::Start: 0x{hr & 0xFFFFFFFF:08X}")
        log.info("[AUDIO] Capture started OK")

        # Write WAV as 16-bit PCM (convert from float if needed)
        wf = wave.open(self._output_path, "wb")
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # always 16-bit output
        wf.setframerate(sample_rate)

        total_frames = 0
        total_packets = 0
        total_silent = 0
        errors = 0

        try:
            while self._running.is_set():
                pkt = c_uint32()
                hr = GetNextPacketSize(cap_ptr, byref(pkt))
                if hr != 0:
                    errors += 1
                    if errors > 100:
                        log.error(f"[AUDIO] Too many errors, last: 0x{hr & 0xFFFFFFFF:08X}")
                        break
                    time.sleep(0.01)
                    continue

                while pkt.value > 0:
                    data_ptr = c_void_p()
                    num_frames = c_uint32()
                    flags_out = ctypes.wintypes.DWORD()
                    dev_pos = ctypes.c_uint64()
                    qpc_pos = ctypes.c_uint64()

                    hr = GetBuffer(cap_ptr, byref(data_ptr), byref(num_frames),
                                   byref(flags_out), byref(dev_pos), byref(qpc_pos))
                    if hr != 0:
                        log.debug(f"[AUDIO] GetBuffer: 0x{hr & 0xFFFFFFFF:08X}")
                        break

                    if num_frames.value > 0:
                        if flags_out.value & AUDCLNT_BUFFERFLAGS_SILENT:
                            wf.writeframes(b"\x00" * (num_frames.value * channels * 2))
                            total_silent += num_frames.value
                        elif data_ptr.value:
                            byte_count = num_frames.value * block_align
                            raw = (ctypes.c_byte * byte_count).from_address(data_ptr.value)
                            raw_bytes = bytes(raw)

                            if is_float and bits == 32:
                                # Convert float32 -> int16
                                n_samples = num_frames.value * channels
                                floats = struct.unpack(f"<{n_samples}f", raw_bytes)
                                int16s = struct.pack(f"<{n_samples}h",
                                    *(max(-32768, min(32767, int(s * 32767))) for s in floats))
                                wf.writeframes(int16s)
                            else:
                                wf.writeframes(raw_bytes)

                        total_frames += num_frames.value
                        total_packets += 1

                    ReleaseBuffer(cap_ptr, num_frames.value)

                    hr = GetNextPacketSize(cap_ptr, byref(pkt))
                    if hr != 0:
                        break

                time.sleep(0.005)
        finally:
            wf.close()
            Stop(client_ptr)
            log.info(f"[AUDIO] Done: {total_frames} frames, {total_packets} packets, "
                     f"{total_silent} silent, {errors} errors, "
                     f"~{total_frames / sample_rate:.1f}s")

    def _record_system(self):
        """Fallback: capture all system audio via pyaudiowpatch WASAPI loopback."""
        import pyaudiowpatch as pyaudio

        p = pyaudio.PyAudio()
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])

            loopback_dev = None
            if default_speakers.get("isLoopbackDevice"):
                loopback_dev = default_speakers
            else:
                for i in range(p.get_device_count()):
                    dev = p.get_device_info_by_index(i)
                    if (dev.get("name", "").startswith(default_speakers["name"])
                            and dev.get("isLoopbackDevice")):
                        loopback_dev = dev
                        break

            if loopback_dev is None:
                log.error("No WASAPI loopback device found")
                return

            sample_rate = int(loopback_dev["defaultSampleRate"])
            channels = loopback_dev["maxInputChannels"]
            log.info(f"System audio capture: {loopback_dev['name']} @ {sample_rate}Hz, {channels}ch")

            chunk_size = sample_rate // 10
            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=sample_rate,
                input=True,
                input_device_index=loopback_dev["index"],
                frames_per_buffer=chunk_size,
            )

            wf = wave.open(self._output_path, "wb")
            wf.setnchannels(channels)
            wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
            wf.setframerate(sample_rate)

            try:
                while self._running.is_set():
                    data = stream.read(chunk_size, exception_on_overflow=False)
                    wf.writeframes(data)
            finally:
                wf.close()
                stream.stop_stream()
                stream.close()
        except Exception as e:
            log.error(f"System audio capture error: {e}")
        finally:
            p.terminate()

    def stop(self):
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=5)
