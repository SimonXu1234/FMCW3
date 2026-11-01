#!/usr/bin/env python3
"""
Analyze a record.bin captured by FMCW3_record.py from the FMCW3 lab build.

File layout (see FMCW3_record.py):
    512-byte info sector ("FMCW" + little-endian params), then a raw byte stream.

FPGA data path (top_module_lab.vhd):
    test counter (12 bit @40 MHz) -> adc.vhd (dual-edge capture, FIR /20)
    -> control.vhd packs one 32-bit word per valid ADC pair:
           word[31:16] = channel A (rising  edge, 16-bit SIGNED)
           word[15:0]  = channel B (falling edge, 16-bit SIGNED)
    -> usb_sync tx FIFO -> FT232H, bytes MSB first: [A>>8, A&0xFF, B>>8, B&0xFF]

The lab build ties usb_tx_full to '0', so the FSM never learns that the
FT232H FIFO is full.  When it is full a byte is silently dropped, and the
4-byte frame stays shifted.  So we track the byte phase per window instead
of assuming one global alignment.

Usage:
    .venv/bin/python pc/analyze_record.py [record.bin] [--no-plot]
"""

import struct
import sys
import numpy as np

args = [a for a in sys.argv[1:] if not a.startswith("--")]
NO_PLOT = "--no-plot" in sys.argv
BIN = args[0] if args else "/home/simon/myProjects/ISAC/FMCW-RADAR-2v2/record.bin"
INFO = 512
LO, HI = -400, 2000          # plausible filtered-ramp sample range (signed)
MAX_DAB = 3                  # |A-B| for one 40 MHz increment of the same sample
W = 1024                     # words per phase-tracking window

# ---------------------------------------------------------------- info sector
raw = open(BIN, "rb").read()
info = raw[:INFO]
assert info[0:4] == b"FMCW", "info sector magic not found"
(ver,) = struct.unpack_from("<I", info, 4)
sweep_time, sweep_gap = struct.unpack_from("<ff", info, 8)
(record_time,) = struct.unpack_from("<I", info, 16)
fs_cfg, n_cfg = struct.unpack_from("<II", info, 20)
f0, bw = struct.unpack_from("<ff", info, 28)

print("=" * 68)
print(f"file        : {BIN}")
print(f"total bytes : {len(raw)}   data bytes: {len(raw)-INFO}")
print(f"info sector : ver={ver} sweep={sweep_time*1e6:.1f}us gap={sweep_gap*1e6:.1f}us "
      f"rec={record_time}s Fs={fs_cfg} N={n_cfg} f0={f0/1e9:.2f}GHz BW={bw/1e6:.0f}MHz")
print("              (only what the PC *asked for*; the lab build ignores config)")

arr = np.frombuffer(raw[INFO:], dtype=np.uint8)
L = len(arr)


def words_at(phase, count):
    """Decode `count` words starting at byte offset `phase`."""
    end = phase + 4 * count
    hi = arr[phase:end:4].astype(np.uint16)
    lo = arr[phase + 1:end:4].astype(np.uint16)
    a = ((hi << 8) | lo).view(np.int16).astype(np.int32)
    hi2 = arr[phase + 2:end:4].astype(np.uint16)
    lo2 = arr[phase + 3:end:4].astype(np.uint16)
    b = ((hi2 << 8) | lo2).view(np.int16).astype(np.int32)
    ok = (a > LO) & (a < HI) & (b > LO) & (b < HI) & (np.abs(a - b) <= MAX_DAB)
    return a, b, ok


# ----------------------------------------------------------- phase tracking
nwin = (L - 4) // (4 * W)
scores = np.zeros((4, nwin), dtype=np.int32)
for p in range(4):
    _, _, ok = words_at(p, nwin * W)
    scores[p] = ok.reshape(nwin, W).sum(axis=1)

phase = scores.argmax(axis=0)
best = scores.max(axis=0)
print(f"\nphase tracking     : {nwin} windows x {W} words")
print(f"  per-window match : mean={best.mean()/W*100:.2f}%  "
      f"min={best.min()/W*100:.1f}%  windows>=95%: {(best>=0.95*W).sum()}/{nwin}")
print(f"  byte phase usage  : {np.bincount(phase, minlength=4).tolist()}")
chg = np.nonzero(np.diff(phase) != 0)[0]
print(f"  byte-frame slips  : {len(chg)} in {nwin*W} words "
      f"(~1 every {nwin*W/max(1,len(chg)):,.0f} words)")

# ------------------------------------------------------- decode segments
# A segment = run of consecutive windows sharing the same byte phase.
segments = []
k = 0
while k < nwin:
    j = k
    while j + 1 < nwin and phase[j + 1] == phase[k]:
        j += 1
    segments.append((k, j, int(phase[k]), int(best[k:j + 1].min())))
    k = j + 1

runs = []
for (k0, k1, p, q) in segments:
    if q < 0.80 * W:           # too dirty, skip
        continue
    base = k0 * W * 4
    a, b, ok = words_at(base + p, (k1 - k0 + 1) * W)
    runs.append((base, a, b, ok))

nw_tot = sum(len(r[1]) for r in runs)
print(f"\nsegments           : {len(segments)} total, {len(runs)} kept "
      f"({nw_tot} words, {100.0*nw_tot*4/(L):.1f}% of the stream)")

if not runs:
    sys.exit("no usable data")

# longest kept segment -> main analysis window
main = max(runs, key=lambda r: len(r[1]))
_, A, B, ok = main
print(f"longest segment    : {len(A)} words")
dAB = np.abs(A - B)
print(f"  A: min={A.min()} max={A.max()} mean={A.mean():.1f}")
print(f"  B: min={B.min()} max={B.max()} mean={B.mean():.1f}")
print(f"  |A-B|<=1 in {100.0*np.mean(dAB<=1):.2f}% of words")

# ------------------------------------------ sawtooth period -> real Fs
dA = np.diff(A)
wrap = np.nonzero(dA < -600)[0]
print(f"\nsawtooth restarts  : {len(wrap)}")
if len(wrap) > 10:
    iv = np.diff(wrap)
    med = int(np.median(iv))
    vals, cnts = np.unique(iv, return_counts=True)
    top = sorted(zip(cnts, vals), reverse=True)[:4]
    print("  period histogram : " + ", ".join(f"{v}x{c}" for c, v in top))
    instr = 4096 / 40e6
    print(f"  test counter     : 12 bit @40 MHz -> {instr*1e6:.2f} us per sawtooth")
    print(f"  measured rate    : {med/instr/1e6:.4f} MSPS "
          f"= {med/instr*4/1e6:.3f} MB/s of payload")
    i0 = int(wrap[len(wrap) // 2]) + 10
    i1 = i0 + med - 20
    ramp = A[i0:i1]
    st = np.diff(ramp)
    fit = np.polyfit(np.arange(len(ramp)), ramp, 1)
    resid = ramp - np.polyval(fit, np.arange(len(ramp)))
    print(f"\none sawtooth (words {i0}..{i1}):")
    print(f"  step per word    : mean={st.mean():.3f} min={st.min()} max={st.max()}")
    print(f"  linear fit       : slope={fit[0]:.4f} counts/word")
    print(f"  residual         : rms={resid.std():.3f} counts  ptp={np.ptp(resid):.1f}")

amp = np.percentile(A, 99.5)
print(f"\nramp amplitude     : ~{amp:.0f} counts for a 4096-count input ramp")
print(f"  => FIR DC gain   : ~{amp/4096:.3f}")

if NO_PLOT:
    sys.exit(0)

# ------------------------------------------------------------------ plots
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots(4, 1, figsize=(12, 11))

n_show = min(2500, len(A))
ax[0].plot(A[:n_show], lw=0.9, label="A (rising edge)")
ax[0].plot(B[:n_show], lw=0.9, alpha=0.5, label="B (falling edge)")
ax[0].set_title(f"longest clean segment, first {n_show} words - filtered 12-bit sawtooth")
ax[0].set_xlabel("word index"); ax[0].set_ylabel("ADC code (signed)")
ax[0].legend(fontsize=8, loc="upper right"); ax[0].grid(alpha=0.3)

z0 = max(0, int(wrap[len(wrap) // 2]) - 25) if len(wrap) > 10 else 0
z1 = min(len(A), z0 + 240)
ax[1].plot(np.arange(z0, z1), A[z0:z1], ".-", ms=2.5, lw=0.7)
ax[1].set_title("zoom across one sawtooth restart (small negative undershoot = FIR ringing)")
ax[1].set_xlabel("word index"); ax[1].set_ylabel("ADC code"); ax[1].grid(alpha=0.3)

st_all = np.diff(A[: min(200000, len(A))])
ax[2].hist(np.clip(st_all, -20, 30), bins=np.arange(-20, 31), log=True)
ax[2].set_title("sample-to-sample step histogram")
ax[2].set_xlabel("A[i+1]-A[i] (clipped +-20)"); ax[2].set_ylabel("count"); ax[2].grid(alpha=0.3)

blk = A[: min(65536, len(A))].astype(float)
blk -= blk.mean()
sp = np.abs(np.fft.rfft(blk * np.hanning(len(blk))))
freqs = np.fft.rfftfreq(len(blk), d=1 / 2.0e6) / 1e3
ax[3].plot(freqs, 20 * np.log10(sp / sp.max() + 1e-12), lw=0.8)
ax[3].set_title(f"spectrum of {len(blk)} words @2 MSPS - sawtooth fundamental 9.77 kHz")
ax[3].set_xlabel("kHz"); ax[3].set_ylabel("dB re max"); ax[3].set_xlim(0, 60)
ax[3].grid(alpha=0.3)

fig.tight_layout()
out = "/home/simon/myProjects/ISAC/FMCW3/pc/record_analysis.png"
fig.savefig(out, dpi=110)
print(f"\nplot saved: {out}")
