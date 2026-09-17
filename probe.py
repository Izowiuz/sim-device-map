#!/usr/bin/env python3
"""Print what a device is doing, live, with the map's own names on it.

The map answers "what is this button" well and "what else moves when I touch
it" not at all, and that gap has cost real time twice now:

- War Thunder's pitch trim went on the VMAX's right throttle lever because the
  axis was unbound and the map said nothing was on it. The two throttle levers
  travel side by side under one hand, so every power change trimmed the
  aircraft.
- The WarBRD's paddle (js 31) and its analogue grip lever (axis 5) are two
  separate entries in the map, and may well be one piece of plastic.

"Free in the plan" and "free under the hand" are different questions. This
tool answers the second: squeeze or press ONE thing, and everything that fires
appears together with the time between events, so a lever whose travel ends in
a switch reads as exactly that.

Run it and touch things. Every event appears as it happens, labelled, with the
gap since the last one -- so a lever whose switch trips early reads as exactly
that, and two axes that move as one show up on the same timestamp. Ctrl-C when
you have seen enough and it summarises what moved together.

    ./probe.py                        # everything connected
    ./probe.py --js /dev/input/js1    # one device
"""

import argparse
import collections
import glob
import os
import struct
import sys
import time

import devicemap

#: A button that closes within this long of an axis moving is very likely the
#: same physical control -- the end of a lever's travel, or a hat that clicks.
TOGETHER = 0.35


def label(dev, kind, num):
    if dev is None:
        return f'{kind} {num}'
    if kind == 'axis':
        a = dev.axis(num)
        g = dev.axis_group(num)
        name = a.label if a else f'axis {num}'
        return f'{name} [{g.label}]' if g else name
    return dev.button_label(num)


def stream(nodes, devs, seconds=None):
    """Print events as they happen; return them for the summary.

    Collecting first and printing afterwards was the wrong shape: you cannot
    tell whether you pressed the thing you meant to until it is too late to
    press it again. Printing live means the trace is a conversation.
    """
    fds = {}
    for js in nodes:
        fds[js] = os.open(js, os.O_RDONLY | os.O_NONBLOCK)
    events, start, rest = [], time.time(), {}
    last = [None]

    def show(js, t, kind, num, val):
        gap = '' if last[0] is None else f'+{t - last[0]:.2f}s'
        last[0] = t
        shown = ({1: 'press', 0: 'release'}.get(val, str(val))
                 if kind == 'button' else str(val))
        tag = f'{os.path.basename(js)} ' if len(nodes) > 1 else ''
        print(f'   {t:6.2f}  {gap:>7}  {tag}{kind:<6} {num:<3} '
              f'{shown:<8} {label(devs[js], kind, num)}', flush=True)

    try:
        while seconds is None or time.time() - start < seconds:
            for js, fd in fds.items():
                try:
                    while True:
                        ev = os.read(fd, 8)
                        if len(ev) < 8:
                            break
                        _t, val, typ, num = struct.unpack('IhBB', ev)
                        now = time.time() - start
                        if typ & 0x80:      # JS_EVENT_INIT, the opening state
                            if typ & 0x02:
                                rest[(js, num)] = val
                            continue
                        if typ & 0x02:
                            # only report an axis that has actually travelled
                            if abs(val - rest.get((js, num), 0)) < 3000:
                                continue
                            rest[(js, num)] = val
                            events.append((js, now, 'axis', num, val))
                            show(js, now, 'axis', num, val)
                        elif typ & 0x01:
                            events.append((js, now, 'button', num, val))
                            show(js, now, 'button', num, val)
                except BlockingIOError:
                    pass
            time.sleep(0.004)
    except KeyboardInterrupt:
        print()
    finally:
        for fd in fds.values():
            os.close(fd)
    return events


#: Two axes reporting within this of each other, again and again, are one
#: control -- or two clamped together, which amounts to the same thing for
#: anyone laying out bindings.
LOCKSTEP = 0.02


def report(devs, events):
    """What moved together, which is the question the trace exists to answer."""
    if not events:
        print('   nothing moved')
        return
    print(f'\n   {len(events)} events')

    pairs = collections.Counter()
    for js, t, kind, num, val in events:
        if kind != 'button' or val != 1:
            continue
        for js2, t2, k2, n2, _v in events:
            if js2 == js and k2 == 'axis' and abs(t2 - t) <= TOGETHER:
                pairs[('contact', js, num, n2)] += 1

    locked = collections.Counter()
    seen = collections.defaultdict(list)
    for js, t, kind, num, val in events:
        if kind == 'axis':
            seen[js].append((t, num, val))
    for js, rows in seen.items():
        for i, (t, num, val) in enumerate(rows):
            for t2, n2, v2 in rows[i + 1:]:
                if t2 - t > LOCKSTEP:
                    break
                if n2 != num and v2 == val:
                    locked[('axes', js, min(num, n2), max(num, n2))] += 1

    if not pairs and not locked:
        print('\n   nothing fired together — separate controls')
        return
    print('\n   moved together — one control, or clamped into one:')
    for (what, js, a, b), n in (pairs + locked).most_common():
        d = devs[js]
        if what == 'contact':
            print(f'     button {a} closes while axis {b} travels   ({n}x)')
            print(f'        {label(d, "button", a)}')
            print(f'        {label(d, "axis", b)}')
        else:
            print(f'     axis {a} and axis {b} report the same value   ({n}x)')
            print(f'        {label(d, "axis", a)}')
            print(f'        {label(d, "axis", b)}')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--js', help='one device, default: all connected')
    ap.add_argument('--seconds', type=float,
                    help='stop after this long; default is until Ctrl-C')
    a = ap.parse_args()

    nodes = [a.js] if a.js else sorted(glob.glob('/dev/input/js*'))
    if not nodes:
        sys.exit('no joystick nodes under /dev/input')
    devs = {}
    for js in nodes:
        info = devicemap.probe(js)
        devs[js] = devicemap.by_usb(info.get('usb') or '')
        d = devs[js]
        print(f'{js}  {d.product if d else info.get("evdev") or "unknown"}')
    print('\nTouch one control at a time. Ctrl-C when done.\n')

    events = stream(nodes, devs, a.seconds)
    report(devs, events)


if __name__ == "__main__" == '__main__':
    main()
