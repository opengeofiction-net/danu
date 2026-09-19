"""isofill as a library, through ctypes.

The binary's in-core path is a call to ``isofill_run``, so a raster filled
through this module is the raster the binary would have written - the same
code, not the same idea of it. The golden test holds both to one reference
anyway, because "would have" is a claim and a test is a fact.

ctypes rather than CFFI, which the spec named: the API is plain C - arrays,
ints, a double - and ctypes is in the standard library, so the editor ships
with one less package on every platform. Nothing about the call needs more.

Where the library is found, in order: ``DANU_ISOFILL_LIB`` if set; beside the
``isofill`` binary on PATH, as ``../lib/libisofill.so`` (``.dll`` on Windows),
which is where ``make install`` puts the pair; then the bare name, for the
platform loader to find on its own paths. There is no stable ABI, so the
library's version must be the one this module was written against, or it is
refused.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .params import Params

# the isofill this module speaks to; extern/isofill's src/isofill.h says the
# same, and a test holds the two equal
EXPECTED_VERSION = '0.7.0'
NO_ELEV = -32768                     # ISOFILL_NO_ELEV in isofill.h
LIB_NAMES = ('libisofill.dll',) if sys.platform == 'win32' else ('libisofill.so',)


class IsofillError(RuntimeError):
    pass


class _Params(ctypes.Structure):
    _fields_ = [('radius', ctypes.c_int), ('barrier', ctypes.c_int),
                ('grad_min', ctypes.c_double), ('pass2', ctypes.c_int),
                ('threads', ctypes.c_int)]


def candidates() -> list[Path]:
    out = []
    env = os.environ.get('DANU_ISOFILL_LIB')
    if env:
        out.append(Path(env))
    exe = shutil.which('isofill')
    if exe:
        base = Path(exe).resolve().parent.parent
        out += [base / 'lib' / n for n in LIB_NAMES] + [base / 'bin' / n for n in LIB_NAMES]
    out += [Path(n) for n in LIB_NAMES]
    return out


@dataclass
class Isofill:
    lib: ctypes.CDLL
    path: Path
    version: str

    @classmethod
    def load(cls) -> 'Isofill':
        errors = []
        for cand in candidates():
            try:
                lib = ctypes.CDLL(str(cand))
            except OSError as e:
                errors.append(f'{cand}: {e}')
                continue
            lib.isofill_version.restype = ctypes.c_char_p
            lib.isofill_version.argtypes = []
            version = lib.isofill_version().decode()
            if version != EXPECTED_VERSION:
                raise IsofillError(f'{cand} is isofill {version}; this build of danu wants {EXPECTED_VERSION}')
            lib.isofill_params_default.restype = None
            lib.isofill_params_default.argtypes = [ctypes.POINTER(_Params)]
            lib.isofill_whole_mb.restype = ctypes.c_double
            lib.isofill_whole_mb.argtypes = [ctypes.c_int, ctypes.c_int]
            lib.isofill_run.restype = ctypes.c_longlong
            lib.isofill_run.argtypes = [
                ctypes.POINTER(ctypes.c_float), ctypes.c_int, ctypes.c_double,
                ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_int, ctypes.c_int, ctypes.POINTER(_Params),
                ctypes.POINTER(ctypes.c_float)]
            return cls(lib, cand, version)
        raise IsofillError('no libisofill could be loaded:\n  ' + '\n  '.join(errors))

    def run(self, constraints: np.ndarray, params: Params, mask: np.ndarray | None = None,
            water: np.ndarray | None = None, nodata: float | None = None,
            pass2: bool = True, threads: int = 0) -> tuple[np.ndarray, int]:
        """Fill. ``constraints`` is rows x cols; cells equal to ``nodata`` (or
        NO_ELEV when None) are unset. Returns (surface float32 rows x cols,
        cells the first pass set)."""
        cons = np.ascontiguousarray(constraints, dtype=np.float32)
        rows, cols = cons.shape
        out = np.empty_like(cons)
        m = w = None
        if mask is not None:
            m = np.ascontiguousarray(mask, dtype=np.uint8)
            if m.shape != cons.shape:
                raise IsofillError(f'mask is {m.shape}, constraints are {cons.shape}')
        if water is not None:
            w = np.ascontiguousarray(water, dtype=np.uint8)
            if w.shape != cons.shape:
                raise IsofillError(f'water is {w.shape}, constraints are {cons.shape}')
        # the binary's defaults, then only what the shell's flags set: radius,
        # barrier and pass 2. grad_min is left as the library has it, exactly
        # as the binary path passes no --grad-min - the same flags and no
        # others, by construction rather than by a copied number
        p = _Params()
        self.lib.isofill_params_default(ctypes.byref(p))
        p.radius = params.fill_cells
        p.barrier = params.barrier_cells
        p.pass2 = int(bool(pass2))
        p.threads = int(threads)
        cptr = lambda a: a.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte)) if a is not None else None  # noqa: E731
        filled = self.lib.isofill_run(
            cons.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            int(nodata is not None), float(nodata if nodata is not None else 0.0),
            cptr(m), cptr(w), cols, rows, ctypes.byref(p),
            out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
        if filled < 0:
            raise IsofillError('isofill_run: ' + ('out of memory' if filled == -2 else 'bad arguments'))
        return out, int(filled)


    def whole_mb(self, cols: int, rows: int) -> float:
        """What the in-core fill holds, as the binary reckons it before
        choosing to band - the binary's own function, so the two cannot
        disagree about where banding begins."""
        return float(self.lib.isofill_whole_mb(cols, rows))

    def default_grad_min(self) -> float:
        """The default the binary uses when no --grad-min is passed."""
        p = _Params()
        self.lib.isofill_params_default(ctypes.byref(p))
        return float(p.grad_min)
