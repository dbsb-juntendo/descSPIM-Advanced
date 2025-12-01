# stage_backends/internal/xa_shared.py
# -*- coding: utf-8 -*-
import os
from contextlib import contextmanager

LIBDIR = r"C:\Program Files\Thorlabs XA\SDK\Native (C, C++)\Libraries\x64"
XAROOT = r"C:\Program Files\Thorlabs XA"

_XA_STARTED = False

# ここに「実体」をあとから詰める
XASDK = None
KDC101 = None
TLMC_OperatingModes = None
TLMC_MoveDirection = None
TLMC_Wait = None
TLMC_ScaleType = None
TLMC_Unit = None
TLMC_StopModes = None
TLMC_JogModes = None
TLMC_JogStopModes = None
TLMC_ChannelEnableStates = None
TLMC_MoveModes = None


@contextmanager
def pushd(p: str):
    cur = os.getcwd()
    os.chdir(p)
    try:
        yield
    finally:
        os.chdir(cur)


def ensure_started():
    """
    XA SDK をプロセス全体で一度だけ startup する。
    """
    global _XA_STARTED
    global XASDK, KDC101
    global TLMC_OperatingModes, TLMC_MoveDirection, TLMC_Wait
    global TLMC_ScaleType, TLMC_Unit, TLMC_StopModes
    global TLMC_JogModes, TLMC_JogStopModes, TLMC_ChannelEnableStates
    global TLMC_MoveModes

    if _XA_STARTED:
        return

    # DLL 検索パスを足す
    os.add_dll_directory(LIBDIR)

    # ここで初めて DLL を叩く import を行う
    from xa_sdk.native_sdks.xa_sdk import XASDK as _XASDK
    from xa_sdk.products.kdc101 import KDC101 as _KDC101
    # XAを使うbackendを作ったら、ここに足す
    
    from xa_sdk.shared.tlmc_type_structures import (
        TLMC_OperatingModes as _TLMC_OperatingModes,
        TLMC_MoveDirection as _TLMC_MoveDirection,
        TLMC_Wait as _TLMC_Wait,
        TLMC_ScaleType as _TLMC_ScaleType,
        TLMC_Unit as _TLMC_Unit,
        TLMC_StopModes as _TLMC_StopModes,
        TLMC_JogModes as _TLMC_JogModes,
        TLMC_JogStopModes as _TLMC_JogStopModes,
        TLMC_ChannelEnableStates as _TLMC_ChannelEnableStates,
        TLMC_MoveModes as _TLMC_MoveModes,
    )

    # モジュール変数に「実体」を詰める
    XASDK = _XASDK
    KDC101 = _KDC101
    TLMC_OperatingModes = _TLMC_OperatingModes
    TLMC_MoveDirection = _TLMC_MoveDirection
    TLMC_Wait = _TLMC_Wait
    TLMC_ScaleType = _TLMC_ScaleType
    TLMC_Unit = _TLMC_Unit
    TLMC_StopModes = _TLMC_StopModes
    TLMC_JogModes = _TLMC_JogModes
    TLMC_JogStopModes = _TLMC_JogStopModes
    TLMC_ChannelEnableStates = _TLMC_ChannelEnableStates
    TLMC_MoveModes = _TLMC_MoveModes

    # ライブラリロード + startup
    with pushd(LIBDIR):
        XASDK.try_load_library(__file__)
    XASDK.startup(XAROOT)

    _XA_STARTED = True


# どこにもつかってない
def shutdown():
    global _XA_STARTED, XASDK
    if not _XA_STARTED or XASDK is None:
        return
    try:
        XASDK.shutdown()
    except Exception:
        pass
    _XA_STARTED = False
