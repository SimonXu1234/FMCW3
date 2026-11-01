#!/usr/bin/env python3
"""
Frame decoder for record.bin captured from the FMCW3 lab build.

Wire format per frame (from control.vhd after the 2026-11-01 change):

    [F0 0D F0 0D]                         <- 4-byte frame header ("magic")
    + 1000 x [A>>8, A&0xFF, B>>8, B&0xFF] <- MAX_ADC_SAMPLES sample pairs
    = 4004 bytes per frame

A (rising edge) and B (falling edge) are int16.  The magic cannot occur in
sample data because every valid sample has A[15:8] = 0x00..0x0F, so 0xF0 in
the high-byte position is impossible.

Why a header: the USB 245-FIFO path can drop/insert a single byte at a USB
transaction boundary.  Rather than requiring a byte-perfect stream, each frame
announces itself, so the PC can resynchronise from anywhere and simply drop the
frames that got damaged.

Usage:
    .venv/bin/python pc/decode_frames.py [record.bin] [--n 1000] [--no-plot]
"""

import struct
import sys
import numpy as np

argv = sys.argv[1:]
NO_PLOT = "--no-plot" in argv
N = None
if "--n" in argv:
    N = int(argv[argv.index("--n") + 1])
pos = [a for a in argv if not a.startswith("--") and not a.isdigit()]
BIN = pos[0] if pos else "/home/simon/myProjects/ISAC/FMCW-RADAR-2v2/record.bin"

INFO, FS = 512, 2_000_000.0
MAGIC = np.array([0xF0, 0x0D, 0xF0, 0x0D], dtype=np.uint8)

raw = open(BIN, "rb").read()
assert raw[:4] == b"FMCW", "not a FMCW record file"
sweep_time, sweep_gap = struct.unpack_from("<ff", raw, 8)
arr = np.frombuffer(raw[INFO:], dtype=np.uint8)

print("=" * 68)
print(f"file        : {BIN}")
print(f"total bytes : {len(raw)}   data bytes: {len(arr)}")

# ------------------------------------------------------------- find headers
hits = np.nonzero(
    (arr[:-3] == MAGIC[0]) & (arr[1:-2] == MAGIC[1])
    & (arr[2:-1] == MAGIC[2]) & (arr[3:] == MAGIC[3])
)[0]
print(f"frame headers found : {len(hits)}")
if len(hits) == 0:
    print("\nNo frame header in this file -> it was recorded with the OLD bitstream.")
    print("Reprogram the board with the new top_module_lab.bit and record again.")
    sys.exit(1)

spacing = np.diff(hits)
sp_med = int(np.median(spacing))
auto_n = (sp_med - 4) // 4
print(f"header spacing      : median={sp_med} bytes  min={spacing.min()}  max={spacing.max()}")
print(f"  => frame length   : {auto_n} sample words per frame "
      f"({sp_med} = 4 header + 4*{auto_n})")
print(f"  spacing == median : {np.mean(spacing == sp_med)*100:.1f}%")
if N is None:
    N = auto_n
    print(f"  using auto-detected N = {N}")
else:
    print(f"  using N = {N} (from --n)")
FRAME_BYTES = 4 + 4 * N

# keep only headers that have a full frame after them
hits = hits[hits + FRAME_BYTES <= len(arr)]
nf = len(hits)
print(f"usable frames       : {nf}")

starts = hits + 4

# ------------------------------------------------- decode, per-frame align
# A single byte slip shifts the 4-byte word grid, so try all 4 byte phases and
# keep, for each frame, the phase that decodes the most valid sample pairs.
idx = starts[:, None] + 4 * np.arange(N)[None, :]          # (nf, N) first byte
A = np.zeros((4, nf, N), dtype=np.int16)
B = np.zeros((4, nf, N), dtype=np.int16)
for p in range(4):
    b0 = arr[idx + p]
    b1 = arr[idx + p + 1]
    b2 = arr[idx + p + 2]
    b3 = arr[idx + p + 3]
    A[p] = (((b0.astype(np.uint16) << 8) | b1)).view(np.int16)
    B[p] = (((b2.astype(np.uint16) << 8) | b3)).view(np.int16)

valid = (np.abs(A.astype(np.int32) - B.astype(np.int32)) <= 4) & (np.abs(A) < 4000)
pstar = valid.sum(axis=2).argmax(axis=0)                       # (nf,)
pick = pstar[None, :, None]
A = np.take_along_axis(A, pick, axis=0)[0]
B = np.take_along_axis(B, pick, axis=0)[0]
align = np.take_along_axis(valid, pick, axis=0)[0]

# frame quality: a real sample pair is a plausible code in BOTH channels.
# (|A-B| is allowed to be large at the sawtooth wrap, so it is not used here.)
inrange = (np.abs(A) < 4000) & (np.abs(B) < 4000)
q = inrange.mean(axis=1)

print(f"byte phase per frame : {np.bincount(pstar, minlength=4).tolist()}")
print(f"alignment score      : mean={align.mean()*100:.2f}%")
print(f"plausible samples    : mean={q.mean()*100:.3f}%   "
      f"frames >=99%: {(q>=0.99).sum()}/{nf} ({100*(q>=0.99).mean():.1f}%)")

R = A[q >= 0.99]
RB = B[q >= 0.99]
print(f"\nframes kept          : {len(R)} x {N}")
if len(R) == 0:
    sys.exit("no clean frame")

print(f"frame[0] sample      : mean={R[:,0].mean():.1f}  "
      f"min={R[:,0].min()} max={R[:,0].max()}  (marker check)")
print(f"frame A range        : min={R.min()} max={R.max()} mean={R.mean():.2f}")
print(f"|A-B|<=1             : {100.0*np.mean(np.abs(R.astype(np.int32)-RB.astype(np.int32))<=1):.2f}% "
      f"(rest are sawtooth-wrap words)")

slopes = np.array([np.polyfit(np.arange(200), f[:200].astype(float), 1)[0] for f in R])
print(f"ramp slope           : first 200 samples, median={np.median(slopes):.4f} "
      f"counts/word (expect ~5.54)")
print(f"chirp rate           : {len(hits)/ (len(arr)/2.7e6):.1f} frames/s (rough), "
      f"header spacing {sp_med} B")

# ------------------------------------------------------------- range FFT
win = np.hanning(N)
S = np.abs(np.fft.rfft((R.astype(float) - R.mean(axis=1, keepdims=True)) * win, axis=1)) ** 2
SdB = 10 * np.log10(S.mean(axis=0) / S.mean(axis=0).max() + 1e-15)
freqs = np.fft.rfftfreq(N, d=1 / FS)
saw = 40e6 / 4096.0

print(f"\ntest-signal fundamental : 40 MHz/4096 = {saw/1e3:.3f} kHz")
print(" strongest peaks (averaged range FFT):")
shown = []
for i in np.argsort(SdB)[::-1]:
    if freqs[i] < 1e3 or any(abs(freqs[i] - f) < 2e3 for f in shown):
        continue
    shown.append(freqs[i])
    print(f"   {freqs[i]/1e3:7.2f} kHz  {SdB[i]:6.1f} dBc  (x{freqs[i]/saw:.2f})")
    if len(shown) >= 8:
        break

if NO_PLOT:
    sys.exit(0)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(4, 1, figsize=(12, 11))

for k in range(min(3, len(R))):
    ax[0].plot(R[k], lw=0.9, label=f"frame {k}")
ax[0].set_title(f"{min(3,len(R))} frames of {N} words @2 MSPS (each frame = one chirp)")
ax[0].set_xlabel("sample index in frame"); ax[0].set_ylabel("ADC code")
ax[0].legend(fontsize=8); ax[0].grid(alpha=0.3)

ax[1].plot(R[0, :60], ".-", ms=4, lw=0.8)
ax[1].set_title("frame 0, first 60 samples - must start at ~0 (frame marker check)")
ax[1].set_xlabel("sample index in frame"); ax[1].set_ylabel("ADC code"); ax[1].grid(alpha=0.3)

ax[2].plot(R[:, 0], ".", ms=3)
ax[2].axhline(0, color="k", lw=0.6)
ax[2].set_title("sample 0 of every kept frame - flat at 0 means the frame grid is right")
ax[2].set_xlabel("frame index"); ax[2].set_ylabel("ADC code"); ax[2].grid(alpha=0.3)

ax[3].plot(freqs / 1e3, SdB, lw=0.9)
for h in range(1, 11):
    ax[3].axvline(h * saw / 1e3, color="r", ls=":", lw=0.6, alpha=0.6)
ax[3].set_title(f"average range-FFT over {len(R)} frames (red = expected sawtooth harmonics)")
ax[3].set_xlabel("kHz"); ax[3].set_ylabel("dBc"); ax[3].set_xlim(0, 60); ax[3].grid(alpha=0.3)

fig.tight_layout()
out = "/home/simon/myProjects/ISAC/FMCW3/pc/frame_analysis.png"
fig.savefig(out, dpi=110)
print(f"\nplot saved: {out}")
