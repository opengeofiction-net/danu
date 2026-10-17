"""Which app macOS takes this process for: NSBundle's main bundle, asked
through the Objective-C runtime. Run through the launcher -

    Danu.app/Contents/MacOS/Danu --python whoami.py

- it is the app's identifier, which is what names the menu bar and the Dock
icon; the app's python3 on its own would be no bundle at all."""

import ctypes
import ctypes.util

objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))
ctypes.cdll.LoadLibrary(ctypes.util.find_library('Foundation'))
objc.objc_getClass.restype = ctypes.c_void_p
objc.sel_registerName.restype = ctypes.c_void_p
objc.objc_msgSend.restype = ctypes.c_void_p
objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]


def send(obj, sel):
    return objc.objc_msgSend(obj, objc.sel_registerName(sel))


bundle = send(objc.objc_getClass(b'NSBundle'), b'mainBundle')
ident = send(bundle, b'bundleIdentifier')
print(ctypes.string_at(send(ident, b'UTF8String')).decode() if ident else '(none)')
