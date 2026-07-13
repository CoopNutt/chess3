"""Synthesized sound effects for Chess 3 — generated with numpy, no files.

All failures (no audio device, numpy missing) degrade to silence, never crash.
"""
import numpy as np
import pygame

_SR = 44100
_cache = {}
_ok = False
_enabled = True
_volume = 0.7


def init():
    """Call once after pygame.init(). Safe to call when audio is unavailable.

    pygame.init() may have pre-opened the mixer with the device's native
    channel count (e.g. 8 on surround setups) — our buffers are stereo, so
    force a 2-channel mixer or every make_sound() would fail silently.
    """
    global _ok
    try:
        cur = pygame.mixer.get_init()
        if cur is not None and (cur[0] != _SR or cur[1] != -16 or cur[2] != 2):
            pygame.mixer.quit()
            cur = None
        if cur is None:
            # allowedchanges=0 forces SDL to CONVERT to our exact stereo
            # format instead of opening the device's native layout (surround
            # devices otherwise reopen at 6/8 channels even when asked for 2)
            pygame.mixer.init(_SR, -16, 2, 512, allowedchanges=0)
        _ok = pygame.mixer.get_init() is not None \
            and pygame.mixer.get_init()[2] == 2
    except Exception:
        _ok = False


def set_enabled(on):
    global _enabled
    _enabled = bool(on)


def set_volume(v):
    global _volume
    _volume = max(0.0, min(1.0, float(v)))


def _seg(freq, dur, vol=0.5, decay=8.0, wave="sine"):
    """One enveloped tone/noise segment as a float array in [-1, 1]."""
    n = max(1, int(_SR * dur))
    t = np.linspace(0.0, dur, n, False)
    if wave == "sine":
        w = np.sin(2 * np.pi * freq * t)
    elif wave == "square":
        w = np.sign(np.sin(2 * np.pi * freq * t)) * 0.6
    elif wave == "noise":
        w = np.random.default_rng(7).uniform(-1.0, 1.0, n)
    else:
        w = np.sin(2 * np.pi * freq * t)
    return w * np.exp(-decay * t) * vol


def _silence(dur):
    return np.zeros(max(1, int(_SR * dur)))


def _mix(*parts):
    """Concatenate segments into one pygame Sound."""
    data = np.concatenate(parts)
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767).astype(np.int16)
    stereo = np.ascontiguousarray(np.column_stack([pcm, pcm]))
    return pygame.sndarray.make_sound(stereo)


def _build(name):
    if name == "turn":          # friendly two-note chime
        return _mix(_seg(660, 0.12, 0.4, 10), _seg(880, 0.22, 0.4, 8))
    if name == "capture":       # solid thud
        return _mix(_seg(170, 0.16, 0.8, 18, "square"),
                    _seg(90, 0.12, 0.5, 20))
    if name == "shoot":         # whip + impact tick
        return _mix(_seg(0, 0.06, 0.5, 30, "noise"),
                    _seg(1400, 0.05, 0.35, 40),
                    _seg(240, 0.08, 0.4, 26, "square"))
    if name == "boom":          # explosion rumble
        return _mix(_seg(0, 0.30, 0.9, 7, "noise"),
                    _seg(60, 0.35, 0.7, 6))
    if name == "win":           # rising fanfare
        return _mix(_seg(523, 0.14, 0.4, 8), _seg(659, 0.14, 0.4, 8),
                    _seg(784, 0.14, 0.4, 8), _seg(1046, 0.4, 0.45, 5))
    if name == "lose":          # sad slide down
        return _mix(_seg(392, 0.2, 0.4, 7), _seg(311, 0.2, 0.4, 7),
                    _seg(233, 0.4, 0.4, 5))
    if name == "invite":        # steam-y ping
        return _mix(_seg(880, 0.09, 0.4, 12), _silence(0.03),
                    _seg(1175, 0.2, 0.4, 9))
    if name == "promote":       # sparkle up
        return _mix(_seg(784, 0.1, 0.35, 12), _seg(1046, 0.1, 0.35, 12),
                    _seg(1568, 0.2, 0.35, 9))
    return _mix(_seg(1000, 0.05, 0.3, 30))


def play(name):
    if not (_ok and _enabled):
        return
    try:
        snd = _cache.get(name)
        if snd is False:        # build failed once; don't retry every call
            return
        if snd is None:
            try:
                snd = _cache[name] = _build(name)
            except Exception:
                _cache[name] = False
                return
        snd.set_volume(_volume)
        snd.play()
    except Exception:
        pass


def works():
    """True when the mixer is usable (for a settings-screen hint)."""
    return _ok
