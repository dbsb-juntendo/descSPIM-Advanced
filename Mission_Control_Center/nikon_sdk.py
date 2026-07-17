# nikon_sdk.py
# -*- coding: utf-8 -*-
# Copyright © 2026 Kiyotada Naitou
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0


import ctypes
from ctypes import (
    c_int, c_uint, c_ushort, c_ubyte, c_short, c_uint64, c_float,
    c_char, c_char_p, c_wchar, c_wchar_p, c_void_p,
    Structure, POINTER, byref, cast, wintypes,
)

from enum import IntEnum

# DLL (stdcall on Windows; 64-bit OK)
NKCAM_DLL_PATH = r"C:\Program Files\Nikon\DS50M-SDK\nkcam.dll"
_nkcam = ctypes.WinDLL(NKCAM_DLL_PATH)

# ここに NKCAM_* 定数 / 構造体 / Nkcam_* プロトタイプを全部そのまま移動
# Calling convention helper (use this when declaring function prototypes later)
NKCAM_STDCALL = ctypes.WINFUNCTYPE  # maps to __stdcall

# Packing (for ctypes.Structure definitions, set _pack_ = NKCAM_PACK)
NKCAM_PACK = 8  # from #pragma pack(push, 8)

# TDIBWIDTHBYTES(bits) -> ((bits + 31) & ~31) // 8
def TDIBWIDTHBYTES(bits: int) -> int:
    return ((int(bits) + 31) & (~31)) // 8

# Constants
NKCAM_MAX               = 128         # minimum device count
NKCAM_EXPOGAIN_DEF      = 100         # exposure gain, default value
NKCAM_EXPOGAIN_MIN      = 100         # exposure gain, minimum value
NKCAM_AETARGET_DEF      = 120         # target of auto exposure
NKCAM_AETARGET_MIN      = 16          # target of auto exposure
NKCAM_AETARGET_MAX      = 220         # target of auto exposure
NKCAM_BLACKLEVEL_MIN    = 0           # minimum black level
NKCAM_BLACKLEVEL8_MAX   = 31          # maximum black level for bit depth = 8
NKCAM_BLACKLEVEL16_MAX  = (31 * 256)  # maximum black level for bit depth = 16
NKCAM_AE_PERCENT_MIN    = 0           # auto exposure percent, 0 => full roi average
NKCAM_AE_PERCENT_MAX    = 100
NKCAM_AE_PERCENT_DEF    = 10

# ===== SDKイベント種別（wParam） =====
class NkcamEvent(IntEnum):
    NKCAM_EVENT_EXPOSURE          = 0x0001
    NKCAM_EVENT_IMAGE             = 0x0004
    NKCAM_EVENT_TRIGGERFAIL       = 0x0007
    NKCAM_EVENT_ROI               = 0x000b
    NKCAM_EVENT_AUTOEXPO_CONV     = 0x000d
    NKCAM_EVENT_AUTOEXPO_CONVFAIL = 0x000e
    NKCAM_EVENT_ERROR             = 0x0080
    NKCAM_EVENT_DISCONNECTED      = 0x0081
    NKCAM_EVENT_NOFRAMETIMEOUT    = 0x0082
    NKCAM_EVENT_EXPO_STOP         = 0x4001
    NKCAM_EVENT_TRIGGER_IN        = 0x4004

# Options
NKCAM_OPTION_BITDEPTH             = 0x06        # Image Format : 0=Y8, 1=Y16
NKCAM_OPTION_TRIGGER              = 0x0b        # Imaging mode : 0=Live, 1=SW Trigger
NKCAM_OPTION_RGB                  = 0x0c        # Image Format : 3=Y8, 4=Y16
NKCAM_OPTION_BLACKLEVEL           = 0x15        # Offset : Y8=0->31. Y16=0->31*256
NKCAM_OPTION_SEQUENCER_ONOFF      = 0x33        # Multiple Exposure Settings : 0=OFF, 1=ON
NKCAM_OPTION_SEQUENCER_NUMBER     = 0x34        # Number of Registered Multiple Exposures : 0->255
NKCAM_OPTION_SEQUENCER_EXPOTIME   = 0x01000000  # Exposure Time for Multiple Exposures : Time Value
NKCAM_OPTION_SEQUENCER_EXPOGAIN   = 0x02000000  # Gain for Multiple Exposures : Gain Value
NKCAM_OPTION_FLUSH                = 0x3d        # Flush the Image : 3
NKCAM_OPTION_EVENT_HARDWARE       = 0x04000000  # HW event : 0=OFF, 1=ON
#   *NKCAM_OPTION_EVENT_HARDWARE
#        - Controls the Enable/Disable of the Entire Event.
#        - Can be Set while Image Transfer is Stopped.
#   *NKCAM_OPTION_EVENT_HARDWARE | NKCAM_EVENT_EXPO_STOP
#        - For Exposure Complete Event.
#   *NKCAM_OPTION_EVENT_HARDWARE | NKCAM_EVENT_TRIGGER_IN
#        - For Device Capture
NKCAM_OPTION_AUTOEXPOSURE_PERCENT = 0x4a        # AE Method : 0 or 100=Average, 1->99=Peak
NKCAM_OPTION_AUTOEXPO_CONV        = 0x50        # Status of AE Convergence : 0=No, 1=Yes, -1=NA(Get Only)
NKCAM_OPTION_AUTOEXPO_TRIGGER     = 0x51        # AE Convergence Processing during Trigger : 0=OFF, 1=ON

# IO Control Types
NKCAM_IOCONTROLTYPE_GET_OUTPUTMODE        = 0x1f  # Get External Output : 0=OFF, 1=ON
NKCAM_IOCONTROLTYPE_SET_OUTPUTMODE        = 0x20  # Set External Output : 0=OFF, 1=ON
NKCAM_IOCONTROLTYPE_GET_EXPO_ACTIVE_MODE  = 0x2f  # Get Exposure Complete External Signal Output Timing : 0=OUT, 1=IN
NKCAM_IOCONTROLTYPE_SET_EXPO_ACTIVE_MODE  = 0x30  # Set Exposure Complete External Signal Output Timing : 0=OUT, 1=IN
NKCAM_IOCONTROLTYPE_GET_EXEVT_ACTIVE_MODE = 0x35  # Get Exposure Complete Event Output Timing : 0=OUT, 1=IN
NKCAM_IOCONTROLTYPE_SET_EXEVT_ACTIVE_MODE = 0x36  # Set Exposure Complete Event Output Timing : 0=OUT, 1=IN


class NkcamResolution(Structure):
    _pack_ = NKCAM_PACK
    _fields_ = [
        ("width",  c_uint),
        ("height", c_uint),
    ]


class NkcamModelV2(Structure):
    _pack_ = NKCAM_PACK
    _fields_ = [
        ("name",        c_wchar_p),                 # const wchar_t*
        ("flag",        c_uint64),                  # unsigned long long
        ("maxspeed",    c_uint),                    # unsigned
        ("preview",     c_uint),                    # unsigned
        ("still",       c_uint),                    # unsigned
        ("maxfanspeed", c_uint),                    # unsigned
        ("ioctrol",     c_uint),                    # unsigned
        ("xpixsz",      c_float),                   # float
        ("ypixsz",      c_float),                   # float
        ("res",         NkcamResolution * 16),      # NkcamResolution[16]
    ]


class NkcamDeviceV2(Structure):
    _pack_ = NKCAM_PACK
    _fields_ = [
        ("displayname", c_wchar * 64),              # wchar_t[64]
        ("id",          c_wchar * 64),              # wchar_t[64]
        ("model",       POINTER(NkcamModelV2)),     # const NkcamModelV2*
    ]


class NkcamFrameInfoV3(Structure):
    _pack_ = NKCAM_PACK
    _fields_ = [
        ("width",        c_uint),
        ("height",       c_uint),
        ("flag",         c_uint),                   # (Not supported)
        ("seq",          c_uint),                   # frame sequence number
        ("timestamp",    c_uint64),                 # microsecond
        ("shutterseq",   c_uint),                   # sequence shutter counter
        ("expotime",     c_uint),                   # exposure time
        ("expogain",     c_ushort),                 # exposure gain
        ("blacklevel",   c_ushort),                 # black level
        ("space",        c_char * 4),

        ("ucCameraType", c_ubyte),
        ("ucImageMode",  c_ubyte),
        ("ucImageColor", c_ubyte),
        ("Exposure_Compensation", c_ubyte),
        ("uiFrameSize",  c_uint),                   # bytes per image
        ("Serial_number", c_char_p),                # char*
        ("FW_version",    c_char_p),                # char*
        ("fpga_version",  c_char_p),                # char*
        ("is_TEC_target",     c_short),             # (Not supported)
        ("TEC_temperature",    c_short),            # (Not supported)
        ("ENV_temperature",    c_short),            # (Not supported)
        ("CHAMBER_temperature",c_short),            # (Not supported)
        ("ENV_humidity",       c_ushort),           # (Not supported)
        ("CHAMBER_humidity",   c_ushort),           # (Not supported)
        ("AE_mode",            c_int),
        ("target_brightness",  c_int),
        ("digital_gain",       c_int),              # (Not supported)
        ("ROI_X_start_position", c_uint),
        ("ROI_Y_start_position", c_uint),
        ("special_trigger_function_counter", c_uint),
        ("light_metering_method", c_uint),
        ("light_metering_area_start_position_X", c_uint),
        ("light_metering_area_start_position_Y", c_uint),
        ("light_metering_area_width",  c_uint),
        ("light_metering_area_height", c_uint),
        ("AE_convergence_or_not", c_uint),
        ("sharpness",      c_uint),                 # (Not supported)
        ("capture_mode",   c_uint),                 # (Not supported)
    ]


class Nkcam_t(Structure):
    _pack_ = NKCAM_PACK
    _fields_ = [("unused", c_int)]

HNkcam = POINTER(Nkcam_t)

# Convenience aliases
HWND   = wintypes.HWND
UINT   = wintypes.UINT
RECT   = wintypes.RECT
# HRESULT = wintypes.HRESULT
HRESULT = ctypes.c_long  # ← これでOK（WindowsのHRESULTはLONG）

# const wchar_t* Nkcam_Version(void);
Nkcam_Version = _nkcam.Nkcam_Version
Nkcam_Version.restype = c_wchar_p
Nkcam_Version.argtypes = []

# unsigned Nkcam_EnumV2(NkcamDeviceV2 arr[NKCAM_MAX]);
Nkcam_EnumV2 = _nkcam.Nkcam_EnumV2
Nkcam_EnumV2.restype = c_uint
Nkcam_EnumV2.argtypes = [POINTER(NkcamDeviceV2)]

# HNkcam Nkcam_Open(const wchar_t* id);
Nkcam_Open = _nkcam.Nkcam_Open
Nkcam_Open.restype = HNkcam
Nkcam_Open.argtypes = [c_wchar_p]

# void Nkcam_Close(HNkcam h);
Nkcam_Close = _nkcam.Nkcam_Close
Nkcam_Close.restype = None
Nkcam_Close.argtypes = [HNkcam]

# HRESULT Nkcam_get_Revision(HNkcam h, unsigned short* pRevision);
Nkcam_get_Revision = _nkcam.Nkcam_get_Revision
Nkcam_get_Revision.restype = HRESULT
Nkcam_get_Revision.argtypes = [HNkcam, POINTER(c_ushort)]

# HRESULT Nkcam_get_SerialNumber(HNkcam h, char sn[32]);
Nkcam_get_SerialNumber = _nkcam.Nkcam_get_SerialNumber
Nkcam_get_SerialNumber.restype = HRESULT
Nkcam_get_SerialNumber.argtypes = [HNkcam, ctypes.POINTER(c_char * 32)]

# HRESULT Nkcam_get_FwVersion(HNkcam h, char fwver[16]);
Nkcam_get_FwVersion = _nkcam.Nkcam_get_FwVersion
Nkcam_get_FwVersion.restype = HRESULT
Nkcam_get_FwVersion.argtypes = [HNkcam, ctypes.POINTER(c_char * 16)]

# HRESULT Nkcam_get_HwVersion(HNkcam h, char hwver[16]);
Nkcam_get_HwVersion = _nkcam.Nkcam_get_HwVersion
Nkcam_get_HwVersion.restype = HRESULT
Nkcam_get_HwVersion.argtypes = [HNkcam, ctypes.POINTER(c_char * 16)]

# HRESULT Nkcam_get_ProductionDate(HNkcam h, char pdate[10]);
Nkcam_get_ProductionDate = _nkcam.Nkcam_get_ProductionDate
Nkcam_get_ProductionDate.restype = HRESULT
Nkcam_get_ProductionDate.argtypes = [HNkcam, ctypes.POINTER(c_char * 10)]

# HRESULT Nkcam_get_FpgaVersion(HNkcam h, char fpgaver[16]);
Nkcam_get_FpgaVersion = _nkcam.Nkcam_get_FpgaVersion
Nkcam_get_FpgaVersion.restype = HRESULT
Nkcam_get_FpgaVersion.argtypes = [HNkcam, ctypes.POINTER(c_char * 16)]

# HRESULT Nkcam_StartPullModeWithWndMsg(HNkcam h, HWND hWnd, UINT nMsg);
Nkcam_StartPullModeWithWndMsg = _nkcam.Nkcam_StartPullModeWithWndMsg
Nkcam_StartPullModeWithWndMsg.restype = HRESULT
Nkcam_StartPullModeWithWndMsg.argtypes = [HNkcam, HWND, UINT]

# HRESULT Nkcam_PullImageV3(HNkcam h, void* pImageData, int bStill, int bits, int rowPitch, NkcamFrameInfoV3* pInfo);
Nkcam_PullImageV3 = _nkcam.Nkcam_PullImageV3
Nkcam_PullImageV3.restype = HRESULT
Nkcam_PullImageV3.argtypes = [HNkcam, c_void_p, c_int, c_int, c_int, POINTER(NkcamFrameInfoV3)]

# HRESULT Nkcam_Stop(HNkcam h);
Nkcam_Stop = _nkcam.Nkcam_Stop
Nkcam_Stop.restype = HRESULT
Nkcam_Stop.argtypes = [HNkcam]

# HRESULT Nkcam_Pause(HNkcam h, int bPause);
Nkcam_Pause = _nkcam.Nkcam_Pause
Nkcam_Pause.restype = HRESULT
Nkcam_Pause.argtypes = [HNkcam, c_int]

# HRESULT Nkcam_Trigger(HNkcam h, unsigned short nNumber);
Nkcam_Trigger = _nkcam.Nkcam_Trigger
Nkcam_Trigger.restype = HRESULT
Nkcam_Trigger.argtypes = [HNkcam, c_ushort]

# HRESULT Nkcam_get_RealTime(HNkcam h, int* val);
Nkcam_get_RealTime = _nkcam.Nkcam_get_RealTime
Nkcam_get_RealTime.restype = HRESULT
Nkcam_get_RealTime.argtypes = [HNkcam, POINTER(c_int)]

# HRESULT Nkcam_put_RealTime(HNkcam h, int val);
Nkcam_put_RealTime = _nkcam.Nkcam_put_RealTime
Nkcam_put_RealTime.restype = HRESULT
Nkcam_put_RealTime.argtypes = [HNkcam, c_int]

# HRESULT Nkcam_get_eSize(HNkcam h, unsigned* pnResolutionIndex);
Nkcam_get_eSize = _nkcam.Nkcam_get_eSize
Nkcam_get_eSize.restype = HRESULT
Nkcam_get_eSize.argtypes = [HNkcam, POINTER(c_uint)]

# HRESULT Nkcam_put_eSize(HNkcam h, unsigned nResolutionIndex);
Nkcam_put_eSize = _nkcam.Nkcam_put_eSize
Nkcam_put_eSize.restype = HRESULT
Nkcam_put_eSize.argtypes = [HNkcam, c_uint]

# HRESULT Nkcam_get_FinalSize(HNkcam h, int* pWidth, int* pHeight);
Nkcam_get_FinalSize = _nkcam.Nkcam_get_FinalSize
Nkcam_get_FinalSize.restype = HRESULT
Nkcam_get_FinalSize.argtypes = [HNkcam, POINTER(c_int), POINTER(c_int)]

# HRESULT Nkcam_get_ResolutionNumber(HNkcam h);
Nkcam_get_ResolutionNumber = _nkcam.Nkcam_get_ResolutionNumber
Nkcam_get_ResolutionNumber.restype = HRESULT
Nkcam_get_ResolutionNumber.argtypes = [HNkcam]

# HRESULT Nkcam_get_Resolution(HNkcam h, unsigned nResolutionIndex, int* pWidth, int* pHeight);
Nkcam_get_Resolution = _nkcam.Nkcam_get_Resolution
Nkcam_get_Resolution.restype = HRESULT
Nkcam_get_Resolution.argtypes = [HNkcam, c_uint, POINTER(c_int), POINTER(c_int)]

# HRESULT Nkcam_get_Roi(HNkcam h, unsigned* pxOffset, unsigned* pyOffset, unsigned* pxWidth, unsigned* pyHeight);
Nkcam_get_Roi = _nkcam.Nkcam_get_Roi
Nkcam_get_Roi.restype = HRESULT
Nkcam_get_Roi.argtypes = [HNkcam, POINTER(c_uint), POINTER(c_uint), POINTER(c_uint), POINTER(c_uint)]

# HRESULT Nkcam_put_Roi(HNkcam h, unsigned xOffset, unsigned yOffset, unsigned xWidth, unsigned yHeight);
Nkcam_put_Roi = _nkcam.Nkcam_put_Roi
Nkcam_put_Roi.restype = HRESULT
Nkcam_put_Roi.argtypes = [HNkcam, c_uint, c_uint, c_uint, c_uint]

# HRESULT Nkcam_get_ExpTimeRange(HNkcam h, unsigned* nMin, unsigned* nMax, unsigned* nDef);
Nkcam_get_ExpTimeRange = _nkcam.Nkcam_get_ExpTimeRange
Nkcam_get_ExpTimeRange.restype = HRESULT
Nkcam_get_ExpTimeRange.argtypes = [HNkcam, POINTER(c_uint), POINTER(c_uint), POINTER(c_uint)]

# HRESULT Nkcam_get_ExpoTime(HNkcam h, unsigned* Time);
Nkcam_get_ExpoTime = _nkcam.Nkcam_get_ExpoTime
Nkcam_get_ExpoTime.restype = HRESULT
Nkcam_get_ExpoTime.argtypes = [HNkcam, POINTER(c_uint)]

# HRESULT Nkcam_put_ExpoTime(HNkcam h, unsigned Time);
Nkcam_put_ExpoTime = _nkcam.Nkcam_put_ExpoTime
Nkcam_put_ExpoTime.restype = HRESULT
Nkcam_put_ExpoTime.argtypes = [HNkcam, c_uint]

# HRESULT Nkcam_get_ExpoAGainRange(HNkcam h, unsigned short* nMin, unsigned short* nMax, unsigned short* nDef);
Nkcam_get_ExpoAGainRange = _nkcam.Nkcam_get_ExpoAGainRange
Nkcam_get_ExpoAGainRange.restype = HRESULT
Nkcam_get_ExpoAGainRange.argtypes = [HNkcam, POINTER(c_ushort), POINTER(c_ushort), POINTER(c_ushort)]

# HRESULT Nkcam_get_ExpoAGain(HNkcam h, unsigned short* Gain);
Nkcam_get_ExpoAGain = _nkcam.Nkcam_get_ExpoAGain
Nkcam_get_ExpoAGain.restype = HRESULT
Nkcam_get_ExpoAGain.argtypes = [HNkcam, POINTER(c_ushort)]

# HRESULT Nkcam_put_ExpoAGain(HNkcam h, unsigned short Gain);
Nkcam_put_ExpoAGain = _nkcam.Nkcam_put_ExpoAGain
Nkcam_put_ExpoAGain.restype = HRESULT
Nkcam_put_ExpoAGain.argtypes = [HNkcam, c_ushort]

# HRESULT Nkcam_get_AutoExpoEnable(HNkcam h, int* bAutoExposure);
Nkcam_get_AutoExpoEnable = _nkcam.Nkcam_get_AutoExpoEnable
Nkcam_get_AutoExpoEnable.restype = HRESULT
Nkcam_get_AutoExpoEnable.argtypes = [HNkcam, POINTER(c_int)]

# HRESULT Nkcam_put_AutoExpoEnable(HNkcam h, int bAutoExposure);
Nkcam_put_AutoExpoEnable = _nkcam.Nkcam_put_AutoExpoEnable
Nkcam_put_AutoExpoEnable.restype = HRESULT
Nkcam_put_AutoExpoEnable.argtypes = [HNkcam, c_int]

# HRESULT Nkcam_get_AutoExpoTarget(HNkcam h, unsigned short* Target);
Nkcam_get_AutoExpoTarget = _nkcam.Nkcam_get_AutoExpoTarget
Nkcam_get_AutoExpoTarget.restype = HRESULT
Nkcam_get_AutoExpoTarget.argtypes = [HNkcam, POINTER(c_ushort)]

# HRESULT Nkcam_put_AutoExpoTarget(HNkcam h, unsigned short Target);
Nkcam_put_AutoExpoTarget = _nkcam.Nkcam_put_AutoExpoTarget
Nkcam_put_AutoExpoTarget.restype = HRESULT
Nkcam_put_AutoExpoTarget.argtypes = [HNkcam, c_ushort]

# HRESULT Nkcam_get_MaxAutoExpoTimeAGain(HNkcam h, unsigned* maxTime, unsigned short* maxGain);
Nkcam_get_MaxAutoExpoTimeAGain = _nkcam.Nkcam_get_MaxAutoExpoTimeAGain
Nkcam_get_MaxAutoExpoTimeAGain.restype = HRESULT
Nkcam_get_MaxAutoExpoTimeAGain.argtypes = [HNkcam, POINTER(c_uint), POINTER(c_ushort)]

# HRESULT Nkcam_put_MaxAutoExpoTimeAGain(HNkcam h, unsigned maxTime, unsigned short maxGain);
Nkcam_put_MaxAutoExpoTimeAGain = _nkcam.Nkcam_put_MaxAutoExpoTimeAGain
Nkcam_put_MaxAutoExpoTimeAGain.restype = HRESULT
Nkcam_put_MaxAutoExpoTimeAGain.argtypes = [HNkcam, c_uint, c_ushort]

# HRESULT Nkcam_get_AEAuxRect(HNkcam h, RECT* pAuxRect);
Nkcam_get_AEAuxRect = _nkcam.Nkcam_get_AEAuxRect
Nkcam_get_AEAuxRect.restype = HRESULT
Nkcam_get_AEAuxRect.argtypes = [HNkcam, POINTER(RECT)]

# HRESULT Nkcam_put_AEAuxRect(HNkcam h, const RECT* pAuxRect);
Nkcam_put_AEAuxRect = _nkcam.Nkcam_put_AEAuxRect
Nkcam_put_AEAuxRect.restype = HRESULT
Nkcam_put_AEAuxRect.argtypes = [HNkcam, POINTER(RECT)]

# HRESULT Nkcam_put_Option(HNkcam h, unsigned iOption, int iValue);
Nkcam_put_Option = _nkcam.Nkcam_put_Option
Nkcam_put_Option.restype = HRESULT
Nkcam_put_Option.argtypes = [HNkcam, c_uint, c_int]

# HRESULT Nkcam_get_Option(HNkcam h, unsigned iOption, int* piValue);
Nkcam_get_Option = _nkcam.Nkcam_get_Option
Nkcam_get_Option.restype = HRESULT
Nkcam_get_Option.argtypes = [HNkcam, c_uint, POINTER(c_int)]

# HRESULT Nkcam_IoControl(HNkcam h, unsigned ioLineNumber, unsigned nType, int outVal, int* inVal);
Nkcam_IoControl = _nkcam.Nkcam_IoControl
Nkcam_IoControl.restype = HRESULT
Nkcam_IoControl.argtypes = [HNkcam, c_uint, c_uint, c_int, POINTER(c_int)]


# ---- I/O control helpers ----
IO_LINE = 3  # ioLineNumber=3 固定

def io_set_outputmode(hcam, on: bool):
    if not hcam:
        return
    val = 1 if on else 0
    hr = Nkcam_IoControl(hcam, c_uint(IO_LINE),
                         c_uint(NKCAM_IOCONTROLTYPE_SET_OUTPUTMODE),
                         c_int(val), None)
    # 失敗時も致命ではないためログのみ
    code = int(hr) & 0xFFFFFFFF
    print(f"[IO] SET_OUTPUTMODE={val} hr=0x{code:08X}")

def io_get_outputmode(hcam) -> int:
    if not hcam:
        return -1
    out = c_int(0)
    hr = Nkcam_IoControl(hcam, c_uint(IO_LINE),
                         c_uint(NKCAM_IOCONTROLTYPE_GET_OUTPUTMODE),
                         c_int(0), byref(out))
    code = int(hr) & 0xFFFFFFFF
    print(f"[IO] GET_OUTPUTMODE -> {out.value} hr=0x{code:08X}")
    return out.value

# ---- simple time conversion helpers ----
def us_to_ms(us: int) -> float:
    """マイクロ秒 → ミリ秒"""
    return us / 1000.0

def ms_to_us(ms: float) -> int:
    """ミリ秒 → マイクロ秒"""
    return max(1, int(round(ms * 1000.0)))
