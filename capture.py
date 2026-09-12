#!/usr/bin/env python3
"""Fill in what the OS cannot tell us: which buttons form a hat, a switch or a
multi-stage trigger, what a lever is, and what you can reach without letting go.

VIRPIL firmware flattens hats into plain buttons, so no amount of probing
recovers the grouping -- it has to be pressed once, by hand, and is then good
forever. This walks through whatever is still `unknown` in a device file and
writes the answers back.

The screen follows the same shape as dcs-bind-wizard: a heading on top, the
thing you are choosing in the middle, and explanation rows pinned above the
footer that change as the cursor moves -- so the vocabulary is in front of you
while you pick it, rather than something to memorise.

    ./capture.py            # pick a connected device and work through it
    ./capture.py --list     # just show what is known, no TUI
"""

import argparse
import curses
import os
import select
import struct
import time

import devicemap

JS_EVENT_BUTTON, JS_EVENT_AXIS, JS_EVENT_INIT = 0x01, 0x02, 0x80

# slug, menu label, direction names, the rows shown while the cursor is on it
KINDS = [
    ('hat2', 'two-way hat or rocker (springs back)', ['up', 'down'],
     ['Two directions, sprung to the centre, often pressing in as well.',
      'The centre sends nothing. Wants a stepped pair -- flaps up and',
      'down, trim up and down -- not one toggle across both.']),
    ('hat4', 'four-way hat', ['up', 'right', 'down', 'left'],
     ['Four directions under one thumb.',
      'Wants four related actions: views, trim, radar.']),
    ('hat8', 'eight-way hat', ['up', 'up-right', 'right', 'down-right',
                               'down', 'down-left', 'left', 'up-left'],
     ['Eight directions. Same idea, more room.',
      'Usually views, where the diagonals earn their keep.']),
    ('trigger', 'multi-stage trigger', ['first', 'second', 'third'],
     ['One squeeze, two or three detents.',
      'Wants fire groups that escalate: guns, then cannon.']),
    ('switch2', 'two-position switch (stays put)', ['one end', 'other end'],
     ['Flips and STAYS where you put it, so a contact is held.',
      'Bind ONE toggle to both ends: every flip changes the state.']),
    ('switch3', 'three-position switch', ['one end', 'centre', 'other end'],
     ['Three detents.',
      'Wants a stepped pair -- flaps up and down -- centre left empty.']),
    ('button', 'single button', [],
     ['A plain momentary button.',
      'What it deserves depends entirely on how you reach it.']),
    ('paddle', 'paddle / pinky lever', [],
     ['Sits under a finger without regripping.',
      'Wants something reflexive: countermeasures.']),
    ('encoder', 'rotary encoder (detents)', ['ccw', 'cw'],
     ['Clicks round rather than sweeping.',
      'Wants trim or zoom, one detent at a time.']),
    ('dial', 'dial / thumbwheel (one axis, maybe a click)', [],
     ['Turns smoothly and reports an axis, not detented buttons.',
      'Often presses in as well. Wants trim, zoom, prop pitch.']),
    ('ministick', 'mini-stick (two axes, maybe a click)', [],
     ['Self-centring thumb stick: two axes and often a press.',
      'Recorded as one control, so the click stays with its axes.']),
    ('selector', 'rotary selector (3+ positions)', [],
     ['One HELD contact per position, one closed at a time.',
      'Sweep it from one end to the other and the order reads itself.',
      'Suits a mode, a master switch, a modifier per position.']),
    ('latch', 'latching lever or flap', [],
     ['Two positions, and it stays where you put it.',
      'The game sees the button HELD, not pressed -- so it suits a state',
      'that is on while the lever is over, not a momentary action.']),
]

REACH = [
    ('thumb, without releasing grip',
     ['The fastest thing you own.', 'Reflex actions belong here.']),
    ('index finger, on the grip',
     ['Trigger territory.', 'Weapons, and nothing you must not hit.']),
    ('middle/ring finger, without releasing grip',
     ['Reachable mid-manoeuvre without regripping.']),
    ('pinky finger, without releasing grip',
     ['Reachable without regripping.',
      'Good for countermeasures and other reflexes.']),
    ('needs letting go',
     ['You have to take a hand off the controls.',
      'Only for things you do with time to spare.']),
    ('unknown',
     ['Leave it open if you are not sure.',
      'Honest beats a guess: a consumer can tell the difference.']),
]

SUITS_VOCAB = [
    ('reflex', ['Hit without thinking, mid-manoeuvre, no regrip.',
                'Countermeasures, WEP.']),
    ('fire', ['A weapon trigger.']),
    ('fire-escalating', ['Stages that escalate: guns, then cannon.']),
    ('release', ['Drop or launch: bombs, rockets.']),
    ('lock', ['Hold to lock a seeker or a radar.']),
    ('sensor', ['Radar and IRST handling: range, mode, next target.']),
    ('view', ['Camera or head movement.']),
    ('trim', ['Trim.']),
    ('toggle', ['A state you flip and leave: gear, airbrake, radar on/off.']),
    ('stepped-pair', ['Step up and down through positions: flaps.']),
    ('occasional', ['You can afford to look for it: engine, map, bay door.']),
    ('guarded', ['Must not be hit by accident: jettison.']),
    ('state', ['On for as long as the lever is over.',
               'Master arm, a modifier, a cover that gates something.']),
]

#: what a freshly captured control starts out ticked as, by shape
SUITS = {
    'hat4': ['view', 'trim', 'sensor'], 'hat8': ['view', 'sensor'],
    'trigger': ['fire-escalating'], 'switch2': ['toggle'],
    'switch3': ['stepped-pair'], 'button': ['occasional'],
    'hat2': ['stepped-pair'],
    'paddle': ['reflex'], 'encoder': ['trim', 'zoom'],
    'latch': ['state'],
    'ministick': ['view', 'cue', 'aim'],
    'selector': ['state'],
    'dial': ['trim', 'zoom'],
}

AXIS_KINDS = [
    ('stick-x', 'main stick, left/right', ['The flying axis.']),
    ('stick-y', 'main stick, fore/aft', ['The flying axis. Wants inverting.']),
    ('twist', 'stick twist', ['Self-centring. Usually rudder.']),
    ('mini-stick-x', 'mini-stick, horizontal',
     ['Self-centring thumb stick.', 'Wants a view, cue or aim pair.']),
    ('mini-stick-y', 'mini-stick, vertical',
     ['Self-centring thumb stick.', 'Wants a view, cue or aim pair.']),
    ('lever', 'lever', ['Stays where you leave it. Throttle, collective.']),
    ('slider', 'slider', ['Resting at minimum makes zero mean off.']),
    ('dial', 'rotary dial', ['Turns. The nicest home for a trim axis.']),
    ('pedal', 'pedal', ['Rudder, or a toe brake.']),
    ('wheel', 'wheel', ['A steering wheel.']),
]

AXIS_SUITS = [
    ('flight-roll', ['Roll.']), ('flight-pitch', ['Pitch.']),
    ('flight-yaw', ['Yaw: rudder, pedals.']),
    ('throttle', ['Engine power.']), ('collective', ['Helicopter collective.']),
    ('brake', ['Wheel brakes. Wants to rest at zero.']),
    ('view', ['Head or camera movement.']),
    ('cue', ['Pointing a radar or IRST antenna.']),
    ('aim', ['Steering a missile or a sight.']),
    ('zoom', ['Zoom. Wants to rest at zero.']),
    ('trim', ['Trim on an axis -- the most comfortable kind there is.']),
    ('prop-pitch', ['Propeller pitch.']), ('sweep', ['Wing sweep.']),
    ('radiator', ['Radiator and cowl flaps.']),
]


# --------------------------------------------------------------------- TUI --

class Tui:
    """Same shape as the one in dcs-bind-wizard, so both feel identical."""

    HELP_ROWS = 3

    def __init__(self, scr):
        self.scr = scr

    def key(self, timeout=0.0):
        deadline = time.monotonic() + timeout
        while True:
            c = self.scr.getch()
            if c == -1:
                if time.monotonic() >= deadline:
                    return None
                time.sleep(0.02)
                continue
            if c in (10, 13, curses.KEY_ENTER):
                return 'enter'
            if c == 27:
                return 'esc'
            if c == curses.KEY_UP:
                return 'up'
            if c == curses.KEY_DOWN:
                return 'down'
            if c in (curses.KEY_BACKSPACE, 127, 8):
                return 'backspace'
            if 32 <= c < 127:
                return chr(c)

    def _put(self, y, x, text, attr=curses.A_NORMAL):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h:
            try:
                self.scr.addstr(y, x, text[:max(0, w - x - 1)], attr)
            except curses.error:
                pass

    def _chrome(self, title, subtitle, help_lines, status, footer):
        """Heading on top; the explanation pinned just above the footer, so it
        never moves while you are looking at the device instead of the screen."""
        h, _ = self.scr.getmaxyx()
        self._put(0, 0, title, curses.A_BOLD)
        if subtitle:
            self._put(1, 0, subtitle)
        for i, line in enumerate(list(help_lines or [])[:self.HELP_ROWS]):
            self._put(h - 3 - self.HELP_ROWS + i, 0, line)
        self._put(h - 2, 0, status or '')
        self._put(h - 1, 0, footer or '')

    def menu(self, title, items, hints=None, subtitle='', index=0,
             multi=False, selected=None, footer=None, status='', quits=False):
        """Arrow through a list; the hint rows follow the cursor.

        Returns an index, or a sorted list of indices when multi, or None.
        """
        selected = set(selected or ())
        index = max(0, min(index, len(items) - 1))
        top = 0
        if footer is None:
            back = 'Q = quit' if quits else 'ESC = back'
            footer = (f'arrows = move, SPACE = tick, RETURN = accept, {back}'
                      if multi else
                      f'arrows = move, RETURN = choose, {back}')
        while True:
            h, _ = self.scr.getmaxyx()
            first = 3 if subtitle else 2
            visible = max(3, h - first - 3 - self.HELP_ROWS)
            if index < top:
                top = index
            elif index >= top + visible:
                top = index - visible + 1
            self.scr.erase()
            for row, i in enumerate(range(top, min(len(items), top + visible))):
                attr = curses.A_REVERSE if i == index else curses.A_NORMAL
                mark = ('[x] ' if i in selected else '[ ] ') if multi else ''
                self._put(first + row, 2, f'{mark}{items[i]}', attr)
            self._chrome(title, subtitle, hints[index] if hints else [],
                         status, footer)
            self.scr.refresh()
            k = self.key(0.5)
            if k == 'up':
                index = (index - 1) % len(items)
            elif k == 'down':
                index = (index + 1) % len(items)
            elif k == 'esc' or (quits and k in ('q', 'Q')):
                return None
            elif k == 'enter':
                return sorted(selected) if multi else index
            elif multi and k == ' ':
                selected.symmetric_difference_update({index})

    def text(self, title, help_lines, default='', subtitle=''):
        value = default
        while True:
            self.scr.erase()
            self._put(3 if subtitle else 2, 2, f'{value}_', curses.A_REVERSE)
            self._chrome(title, subtitle, help_lines,
                         f'default: {default}' if default else '',
                         'type, RETURN = accept, ESC = back')
            self.scr.refresh()
            k = self.key(0.5)
            if k is None:
                continue
            if k == 'enter':
                return value or default
            if k == 'esc':
                return None
            if k == 'backspace':
                value = value[:-1]
            elif len(k) == 1 and k.isprintable():
                value += k

    def confirm(self, title, lines, help_lines=(), default=True):
        while True:
            self.scr.erase()
            for i, ln in enumerate(lines):
                self._put(2 + i, 2, ln)
            self._chrome(title, '', help_lines, '',
                         'Y = yes, N = no, ESC = back')
            self.scr.refresh()
            k = self.key(0.5)
            if k in ('y', 'Y'):
                return True
            if k in ('n', 'N'):
                return False
            if k == 'esc':
                return None
            if k == 'enter':
                return default


# ------------------------------------------------------------- joystick io --

def drain(fd):
    """Swallow the synthetic initial-state burst the kernel sends on open."""
    while select.select([fd], [], [], 0.15)[0]:
        try:
            os.read(fd, 8 * 128)
        except BlockingIOError:
            return


def _events(fd):
    try:
        data = os.read(fd, 8 * 128)
    except BlockingIOError:
        return
    for i in range(0, len(data), 8):
        _, val, typ, num = struct.unpack('<IhBB', data[i:i + 8])
        if typ & JS_EVENT_INIT:
            continue
        yield typ, num, val


def collect_buttons(tui, fd, title, help_lines):
    """Buttons pressed, in first-press order, until RETURN.

    Also reports which are still closed at that moment: a switch that stays put
    leaves one held, a sprung one leaves none, and that is the whole difference
    between two shapes that look identical on the way in.
    """
    seen, held = [], set()
    while True:
        tui.scr.erase()
        tui._put(2, 2, 'press every part of ONE control, then RETURN',
                 curses.A_BOLD)
        for i, b in enumerate(seen):
            tui._put(4 + i, 4, f'button {b}')
        tui._chrome(title, '', help_lines,
                    f'{len(seen)} so far' if seen else '',
                    'RETURN = done, ESC = cancel')
        tui.scr.refresh()
        if select.select([fd], [], [], 0.05)[0]:
            for typ, num, val in _events(fd):
                if typ & JS_EVENT_BUTTON:
                    if val:
                        held.add(num)
                        if num not in seen:
                            seen.append(num)
                    else:
                        held.discard(num)
        k = tui.key(0)
        if k == 'enter':
            return seen, held
        if k == 'esc':
            return None, set()


def one_button(tui, fd, title, prompt, help_lines):
    """Wait for a single press. RETURN skips and returns None."""
    while True:
        tui.scr.erase()
        tui._put(2, 2, prompt, curses.A_BOLD)
        tui._chrome(title, '', help_lines, '',
                    'press it, or RETURN to skip')
        tui.scr.refresh()
        if select.select([fd], [], [], 0.05)[0]:
            for typ, num, val in _events(fd):
                if typ & JS_EVENT_BUTTON and val:
                    return num
        k = tui.key(0)
        if k in ('enter', 'esc'):
            return None


def classify_travel(values):
    """Analogue, or a hat pretending to be an axis?

    A mini-hat wired to axes only ever reports its extremes and centre, so an
    action wanting proportional control -- aiming, head movement -- gets three
    positions instead of a sweep. Worth knowing before binding one.
    """
    if len(values) < 3:
        return ''
    inner = [v for v in values if 6000 < abs(v) < 26000]
    return 'stepped' if len(set(values)) <= 5 and not inner else 'analog'


def one_axis(tui, fd, title, help_lines):
    """Whichever axis moves furthest from where it started.

    Returns (index, travel) -- travel says whether it sweeps or steps.
    """
    start, moved, seen = {}, {}, {}
    while True:
        best = max(moved, key=moved.get) if moved else None
        travel = classify_travel(seen.get(best, [])) if best is not None else ''
        tui.scr.erase()
        tui._put(2, 2, 'move ONE axis through its full travel, then RETURN',
                 curses.A_BOLD)
        if best is not None:
            tui._put(4, 4, f'axis {best}   (travel seen: {moved[best]})')
            if travel:
                tui._put(5, 4, 'reports a continuous sweep' if travel == 'analog'
                         else 'reports only its extremes -- a hat on an axis')
        tui._chrome(title, '', help_lines, '', 'RETURN = accept, ESC = cancel')
        tui.scr.refresh()
        if select.select([fd], [], [], 0.05)[0]:
            for typ, num, val in _events(fd):
                if typ & JS_EVENT_AXIS:
                    start.setdefault(num, val)
                    moved[num] = max(moved.get(num, 0), abs(val - start[num]))
                    seen.setdefault(num, []).append(val)
        k = tui.key(0)
        if k == 'enter':
            return (best, travel) if best is not None else (None, '')
        if k == 'esc':
            return None, ''


# ------------------------------------------------------------------ writing --

def esc(s):
    return s.replace('\\', '\\\\').replace('"', '\\"')


def emit_str(key, val, pad=7):
    if '\n' in val or len(val) > 86:
        body = val.replace('\\', '\\\\').replace('"""', '\\"\\"\\"')
        return f'{key:<{pad}}= """{body}"""'
    return f'{key:<{pad}}= "{esc(val)}"'


def emit_list(key, vals, pad=7):
    if vals and isinstance(vals[0], str):
        inner = ', '.join(f'"{esc(v)}"' for v in vals)
    else:
        inner = ', '.join(str(v) for v in vals)
    return f'{key:<{pad}}= [{inner}]'


def write_device(dev):
    """Rewrite the file: keep its leading comment block, re-emit the rest."""
    src = open(dev.path, encoding='utf-8').read()
    header = src.split('[device]', 1)[0].rstrip() + '\n\n'
    raw = dev._raw
    out = [header, '[device]']
    for k in ('slug', 'product', 'vendor', 'kind', 'hand'):
        if raw['device'].get(k):
            out.append(emit_str(k, raw['device'][k], 8))
    for k in ('buttons', 'axes'):
        out.append(f'{k:<8}= {raw["device"][k]}')

    ident = raw.get('identity', {})
    if isinstance(ident, dict):
        ident = [ident] if ident else []
    for k, one in enumerate(ident):
        out.append('\n[[identity]]')
        pad = max(7, max((len(k) for k in one if k != 'games'), default=6) + 1)
        for key in ('usb', 'serial'):
            if one.get(key):
                out.append(emit_str(key, one[key], pad))
        if one.get('evdev'):
            out.append('# Contains the firmware build date -- do not match on it.')
            out.append(emit_str('evdev', one['evdev'], pad))
        if one.get('first_seen'):
            out.append(emit_str('first_seen', one['first_seen'], pad))
        if one.get('games'):
            out.append('\n[identity.games]')
            w = max(len(g) for g in one['games'])
            for g, v in one['games'].items():
                out.append(emit_str(g, v, w + 1))

    fp = raw.get('fingerprint') or {}
    if fp:
        out.append('\n# Survives an identity change, so the same hardware is still')
        out.append('# recognisable after a reconfiguration -- and a change HERE means')
        out.append('# the buttons may have moved, which makes the grouping suspect.')
        out.append('[fingerprint]')
        for key in ('buttons', 'axes'):
            if fp.get(key) is not None:
                out.append(f'{key:<8}= {fp[key]}')
        for key in ('axmap', 'hid'):
            if fp.get(key):
                out.append(emit_list(key, list(fp[key]), 8))

    out.append('\n# --------------------------------------------------------------------- axes')
    for a in raw.get('axis', []):
        out.append('\n[[axis]]')
        out.append(f'index  = {a["index"]}')
        for k in ('evdev', 'hid', 'rest', 'travel', 'kind', 'label'):
            if a.get(k):
                out.append(emit_str(k, a[k]))
        if a.get('suits'):
            out.append(emit_list('suits', a['suits']))
        if a.get('note'):
            out.append(emit_str('note', a['note']))
        out.append(emit_str('source', a.get('source', 'unknown')))

    out.append('\n# ------------------------------------------------------------------ buttons')
    groups = sorted(raw.get('group', []), key=lambda g: (g['kind'] == 'unknown',
                                                         min(g['buttons']) if g['buttons'] else 0))
    for g in groups:
        out.append('\n[[group]]')
        out.append(emit_str('kind', g['kind']))
        out.append(emit_list('buttons', g['buttons']))
        for k in ('dirs', 'stages', 'positions'):
            if g.get(k):
                out.append(emit_list(k, g[k]))
        if g.get('push') is not None:
            out.append(f'{"push":<7}= {g["push"]}')
        if g.get('cumulative'):
            out.append(f'{"cumulative":<7}= true')
        if g.get('rest_contact') is not None:
            out.append(f'{"rest_contact":<7}= {g["rest_contact"]}')
        if g.get('transient'):
            out.append(emit_list('transient', list(g['transient'])))
        if g.get('axes'):
            out.append(emit_list('axes', list(g['axes'])))
        for k in ('label', 'reach', 'rest'):
            if g.get(k):
                out.append(emit_str(k, g[k]))
        if g.get('suits'):
            out.append(emit_list('suits', g['suits']))
        if g.get('note'):
            out.append(emit_str('note', g['note']))
        out.append(emit_str('source', g.get('source', 'unknown')))

    tmp = dev.path + '.tmp'
    open(tmp, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    import tomllib
    with open(tmp, 'rb') as f:              # never leave a broken file behind
        tomllib.load(f)
    os.replace(tmp, dev.path)


# -------------------------------------------------------------------- flow

# -------------------------------------------------------------------- flow --

def unknown_group(raw):
    """The bucket of not-yet-captured buttons, created if it was emptied."""
    g = next((x for x in raw['group'] if x['kind'] == 'unknown'), None)
    if g is None:
        g = {'kind': 'unknown', 'buttons': [], 'label': 'Not yet captured',
             'source': 'unknown'}
        raw['group'].append(g)
    return g


def reconcile(raw, n_buttons):
    """Every button belongs to exactly one group. Anything that fell out of the
    bookkeeping goes back to the unknown pool rather than silently vanishing
    and reading as described."""
    claimed = {}
    for g in raw['group']:
        if g['kind'] == 'unknown':
            continue
        for b in all_of(g):
            claimed.setdefault(b, g)
    missing = sorted(set(range(n_buttons)) - set(claimed))
    u = next((g for g in raw['group'] if g['kind'] == 'unknown'), None)
    if missing:
        if u is None:
            u = {'kind': 'unknown', 'label': 'Not yet captured',
                 'source': 'unknown', 'buttons': []}
            raw['group'].append(u)
        u['buttons'] = missing
    elif u is not None:
        raw['group'].remove(u)
    return missing


def all_of(g):
    out = list(g['buttons'])
    for k in ('push', 'rest_contact'):
        if g.get(k) is not None:
            out.append(g[k])
    out.extend(g.get('transient') or [])
    return out


def analyse_selector(events):
    """Read a rotary selector off one sweep.

    Each position holds its own contact, so the one you START on never sends a
    press -- it is already closed, and gives itself away by opening. Sweep from
    one end to the other and the order falls out: the contact that opens first
    is position 1, then each contact in the order it closes.
    """
    first, downs, ups = {}, {}, {}
    for t, b, down in events:
        first.setdefault(b, down)
        if down:
            downs.setdefault(b, t)
        else:
            ups.setdefault(b, t)
    start = sorted((b for b in first if first[b] is False),
                   key=lambda b: ups[b])
    rest = sorted((b for b in downs if b not in start), key=lambda b: downs[b])
    order = start[:1] + rest
    # exactly one closed at a time is what makes it a selector rather than a
    # handful of buttons that happen to be near each other
    exclusive = True
    closed = set(start[:1])
    for t, b, down in events:
        if down:
            closed.add(b)
        else:
            closed.discard(b)
        if len(closed) > 1:
            exclusive = False
    return {'order': order, 'exclusive': exclusive}


def observe_selector(tui, fd, title):
    events = []
    t0 = time.monotonic()
    while True:
        got = analyse_selector(events)
        tui.scr.erase()
        tui._put(2, 2, 'start at one end, sweep to the other, then RETURN',
                 curses.A_BOLD)
        for i, b in enumerate(got['order']):
            tui._put(4 + i, 4, f'position {i + 1}:  button {b}')
        if got['order'] and not got['exclusive']:
            tui._put(5 + len(got['order']), 4,
                     'more than one closed at once -- not a selector?')
        tui._chrome(title, '',
                    ['The position you start on never sends a press: its',
                     'contact is already closed and only shows itself by',
                     'opening. That is what puts it first.'],
                    f'{len(events)} events', 'RETURN = done, ESC = cancel')
        tui.scr.refresh()
        if select.select([fd], [], [], 0.05)[0]:
            for typ, num, val in _events(fd):
                if typ & JS_EVENT_BUTTON:
                    events.append((time.monotonic() - t0, num, bool(val)))
        k = tui.key(0)
        if k == 'esc':
            return None
        if k == 'enter' and len(got['order']) > 1:
            return got


def analyse_trigger(events):
    """Work a trigger out from one pull and release.

    Three things come out of the timing that presses alone cannot show:

    - a REST contact is closed while the trigger is untouched, so its first
      event is an `up` and it closes again at the end;
    - STAGES nest -- each deeper one goes down inside the one before it and
      comes up first -- which is what makes them cumulative;
    - a TRANSIENT contact closes only over a band of the travel, so it fires
      on the way in and again on the way back out.
    """
    downs, ups, n_down = {}, {}, {}
    first = {}
    for t, b, down in events:
        first.setdefault(b, down)
        if down:
            n_down[b] = n_down.get(b, 0) + 1
            downs.setdefault(b, t)
        else:
            ups.setdefault(b, t)

    rest = next((b for b in first if first[b] is False), None)
    rest_last = None
    for t, b, down in reversed(events):
        if b == rest and down:
            rest_last = t
            break
    if rest is not None and rest_last is None:
        rest = None                      # went up and never came back: not it

    # anything that fired more than once during one cycle is passing through
    transient = sorted(b for b in n_down
                       if b != rest and n_down[b] > 1)

    rest_of = [b for b in downs if b != rest and b not in transient]
    stages = sorted(rest_of, key=lambda b: downs[b])
    # a stage must sit inside the one before it; if it does not, it is passing
    # through as well
    clean = []
    for b in stages:
        if not clean:
            clean.append(b)
            continue
        prev = clean[-1]
        if downs[prev] < downs[b] and ups.get(prev, 9e9) > ups.get(b, 0):
            clean.append(b)
        else:
            transient.append(b)
    transient = sorted(set(transient))
    cumulative = len(clean) > 1
    return {'stages': clean, 'rest': rest, 'transient': transient,
            'cumulative': cumulative}


def observe_trigger(tui, fd, title):
    """Watch one full pull and release, and read the trigger off the timing."""
    events = []
    t0 = time.monotonic()
    while True:
        got = analyse_trigger(events)
        tui.scr.erase()
        tui._put(2, 2, 'pull it all the way and let go, then RETURN',
                 curses.A_BOLD)
        y = 4
        for i, b in enumerate(got['stages']):
            tui._put(y, 4, f'stage {i + 1}:       button {b}')
            y += 1
        if got['rest'] is not None:
            tui._put(y, 4, f'rest contact:  button {got["rest"]}'
                           f'   (closed when untouched)')
            y += 1
        for b in got['transient']:
            tui._put(y, 4, f'passing:       button {b}'
                           f'   (fires again on the way out)')
            y += 1
        tui._chrome(title, '',
                    ['Stages that nest are cumulative: pulling through fires',
                     'everything bound up to that stage. A rest or passing',
                     'contact is recorded but never offered for binding.'],
                    f'{len(events)} events', 'RETURN = done, ESC = cancel')
        tui.scr.refresh()

        if select.select([fd], [], [], 0.05)[0]:
            for typ, num, val in _events(fd):
                if typ & JS_EVENT_BUTTON:
                    events.append((time.monotonic() - t0, num, bool(val)))
        k = tui.key(0)
        if k == 'esc':
            return None
        if k == 'enter' and got['stages']:
            if got['rest'] is not None:
                b = got['rest']
                answer = tui.confirm(
                    title,
                    [f'Button {b} was closed before you touched the trigger,',
                     'and closed again by the end.', '',
                     'Does it come back on its own when you let go?'],
                    ['Yes -- it is the trigger\'s own rest contact.',
                     'No, you push it back -- it is a separate latching lever,',
                     'and it gets captured on its own.'])
                if answer is None:
                    continue
                if not answer:
                    got['rest'] = None
            return got


def capture_ministick(tui, dev, fd, click=None, first_axis=None,
                      first_vertical=False, kind='ministick', n_axes=2):
    """Anything that owns axes and often a click: a mini-stick is two axes, a
    dial is one. Reachable from either side -- press it and pick the shape, or
    move it and say yes."""
    raw = dev._raw
    head = f'{dev.product} — {"dial" if kind == "dial" else "mini-stick"}'

    if click is None:
        drain(fd)
        click = one_button(tui, fd, head, 'does it click? press it in',
                           ['A wheel or stick that presses in reports one more',
                            'button. RETURN skips if this one does not click.'])

    # slot 0 is the horizontal direction, slot 1 the vertical: a mini-stick is
    # two SEPARATE axes and the map has to know which number is which
    slots = [None] * n_axes
    if first_axis is not None:
        slots[1 if (first_vertical and n_axes > 1) else 0] = first_axis
    names = ['side to side', 'up and down'] if n_axes > 1 else ['round']

    while None in slots:
        i = slots.index(None)
        other = next((v for v in slots if v is not None), None)
        drain(fd)
        a, travel = one_axis(tui, fd, head, [
            f'Turn it {names[i]}.' if n_axes == 1 else
            f'Move it {names[i]} -- this is the'
            f' {"second" if other is not None else "first"} of its two axes.',
            'Each direction is its own axis with its own number.'
            if n_axes > 1 else 'Turn it end to end so it can be told apart.',
            f'Already have axis {other} for {names[1 - i]}.'
            if other is not None else ''])
        if a is None:
            return False
        if a in slots:
            tui.confirm(head,
                        [f'That is axis {a} again -- the one already recorded'
                         f' for {names[1 - i]}.', '',
                         f'Move it {names[i]} instead.'],
                        ['The two directions have to be two different axes.',
                         'If it only ever moves one axis, it is not a'
                         ' mini-stick.'], default=True)
            continue
        slots[i] = a
        if travel:
            ax = next((x for x in raw.get('axis', []) if x['index'] == a), None)
            if ax is None:
                ax = {'index': a}
                raw.setdefault('axis', []).append(ax)
            ax['travel'] = travel
    axes = slots

    label = tui.text(f'{head} — name it',
                     ['What you would call it looking at the device.'],
                     'Dial' if kind == 'dial' else 'Mini-stick')
    if label is None:
        return False
    ri = tui.menu(f'{head} — how do you reach it?', [r[0] for r in REACH],
                  [r[1] for r in REACH], subtitle=label, index=0)
    if ri is None:
        return False
    pre = [i for i, (v, _) in enumerate(SUITS_VOCAB)
           if v in SUITS.get(kind, [])]
    si = tui.menu(f'{head} — what kind of action belongs here?',
                  [v for v, _ in SUITS_VOCAB], [h for _, h in SUITS_VOCAB],
                  subtitle=label, multi=True, selected=pre)
    if si is None:
        return False

    entry = {'kind': kind, 'buttons': [], 'label': label,
             'reach': REACH[ri][0], 'axes': axes,
             'suits': [SUITS_VOCAB[i][0] for i in si], 'source': 'measured'}
    if click is not None:
        entry['push'] = click
    # replace anything that already claimed these axes or that button -- but
    # never the unknown pool, whose all_of() is every button left to capture
    for g in [g for g in raw['group']
              if g['kind'] != 'unknown'
              and ((click is not None and click in all_of(g))
                   or set(g.get('axes') or []) & set(axes))]:
        raw['group'].remove(g)
    raw['group'].append(entry)
    if click is not None:
        u = unknown_group(raw)
        u['buttons'] = [b for b in u['buttons'] if b != click]
        if not u['buttons']:
            raw['group'].remove(u)
    for i in axes:
        ax = next((x for x in raw.get('axis', []) if x['index'] == i), None)
        if ax is not None and ax.get('source') != 'measured':
            ax['source'] = 'measured'
            ax.pop('note', None)
    return True


def capture_button(tui, dev, fd):
    """One physical control, from press to written entry.  Returns True if
    anything changed."""
    raw = dev._raw
    head = f'{dev.product} — new control'
    drain(fd)
    seen, held = collect_buttons(tui, fd, head, [
        'A hat: push every direction in turn, then RETURN.',
        'A two-stage trigger: squeeze through both detents.',
        'A switch that stays put: leave it in the position you mean.'])
    if not seen:
        return False

    unknown = unknown_group(raw)
    touched = [g for g in raw['group'] if g['kind'] != 'unknown'
               and any(b in all_of(g) for b in seen)]
    if touched:
        lines = ['These buttons already belong to:', '']
        for g in touched:
            lines.append(f'   {g["kind"]:16s} {all_of(g)}  '
                         f'{g.get("label", "")}   (source: {g.get("source")})')
        lines += ['', f'You just pressed: {seen}']
        measured = any(g.get('source') == 'measured' for g in touched)
        lines += ['', 'Y -- replace it with what you just pressed',
                  'N -- leave it alone and describe the rest']
        warn = ['Most seeded grouping is inferred -- a guess from another game.',
                'Replacing it with what your hand just did is the point.']
        if measured:
            warn = ['One of those was captured by hand, not guessed.',
                    'A control that mechanically nudges another shows up in its',
                    'trace -- that is what N is for. RETURN says N.']
        replace = tui.confirm(head, lines, warn, default=not measured)
        if replace is None:
            return False
        if replace:
            freed = [b for g in touched for b in all_of(g)]
            for g in touched:
                raw['group'].remove(g)
            back = sorted(set(freed) - set(seen))
            if back:
                unknown['buttons'] = sorted(set(unknown['buttons']) | set(back))
        # answering N keeps them: the `stolen` check below drops those buttons
        # from the new entry instead of taking them

    ki = tui.menu(f'{head} — what is it?', [k[1] for k in KINDS],
                  [k[3] for k in KINDS], subtitle=f'buttons: {seen}', index=5)
    if ki is None:
        return False
    kind, _, dirnames, _ = KINDS[ki]

    stays = ('switch2', 'switch3', 'latch', 'selector')
    if kind in stays and not held:
        if not tui.confirm(head,
                           ['Nothing is closed right now.', '',
                            f'A {kind} holds a contact in the position it is',
                            'left in -- this one sprang back.', '',
                            'Carry on anyway?'],
                           ['A sprung two-way lever is a rocker, not a switch.'],
                           default=False):
            return False
    if kind not in stays and held:
        if not tui.confirm(head,
                           [f'Button {sorted(held)} is still closed.', '',
                            f'A {kind} is momentary -- nothing should be held',
                            'once your hand is off it.', '',
                            'Carry on anyway?'],
                           ['Something that stays put is a switch, a latch or',
                            'a selector.'], default=False):
            return False

    order, push, rest_contact, cumulative = list(seen), None, None, False
    transient, dirs = [], []

    if kind == 'hat2':
        ways = [('up', 'down'), ('left', 'right'), ('forward', 'back')]
        oi = tui.menu(f'{head} — which way does it move?',
                      ['up and down', 'left and right', 'forward and back'],
                      [['Vertical, the usual for a flap or trim lever.'],
                       ['Across, like a thumb rocker on a throttle.'],
                       ['Along the grip, away from you and back.']],
                      subtitle=f'buttons: {seen}')
        if oi is None:
            return False
        dirnames = list(ways[oi])
    if kind == 'selector':
        drain(fd)
        got = observe_selector(tui, fd, head)
        if got is None:
            return False
        order = got['order']
        dirs = [str(i + 1) for i in range(len(order))]
    if kind == 'trigger':
        drain(fd)
        got = observe_trigger(tui, fd, head)
        if got is None:
            return False
        order, rest_contact = got['stages'], got['rest']
        cumulative, transient = got['cumulative'], got['transient']
    if kind in ('hat2', 'hat4', 'hat8', 'encoder', 'ministick', 'dial'):
        push = one_button(tui, fd, head, 'does it also click? press the click in',
                          ['A hat, an encoder and a mini-stick often press in.',
                           'That click reports as one more button.',
                           'RETURN skips if this one does not click.'])
        if push is not None and push in order:
            order.remove(push)

    control_axes = []
    if kind in ('ministick', 'dial'):
        return capture_ministick(
            tui, dev, fd, kind=kind, n_axes=1 if kind == 'dial' else 2,
            click=push if push is not None
            else (seen[0] if len(seen) == 1 else None))

    expect = {'hat2': 2, 'hat4': 4, 'hat8': 8,
              'switch2': 2, 'switch3': 3}.get(kind)
    if kind in ('trigger', 'ministick', 'selector'):
        expect = None
    if expect and len(order) != expect:
        if not tui.confirm(head,
                           [f'{len(order)} directions for a {kind}, expected'
                            f' {expect}.', '', f'directions: {order}',
                            f'push: {push}' if push is not None else ''],
                           ['Carry on only if you meant it.']):
            return False

    if kind == 'trigger':
        dirs = dirnames[:len(order)]
    if kind not in ('trigger', 'selector') and dirnames and len(order) > 1:
        want = dirnames[:len(order)]
        picked = []
        for d in want:
            b = one_button(tui, fd, head, f'press:  {d.upper()}',
                           ['Directions are physical, from your seat:',
                            'UP is away from you, toward the nose.',
                            'RETURN keeps the order you first pressed them in.'])
            if b is None:
                picked = []
                break
            picked.append(b)
        if picked and sorted(picked) == sorted(order):
            order = picked
        dirs = want

    label = tui.text(f'{head} — name it',
                     ['What you would call it looking at the device.',
                      'Hat A, Trigger, Gear switch, Pinky button.'],
                     {'hat4': 'Hat', 'hat8': 'Hat',
                      'switch2': 'Two-position switch',
                      'switch3': 'Three-position switch', 'trigger': 'Trigger',
                      'hat2': 'Hat', 'paddle': 'Paddle'}.get(kind, 'Button'))
    if label is None:
        return False

    ri = tui.menu(f'{head} — how do you reach it?', [r[0] for r in REACH],
                  [r[1] for r in REACH], subtitle=label, index=len(REACH) - 1)
    if ri is None:
        return False

    pre = [i for i, (v, _) in enumerate(SUITS_VOCAB) if v in SUITS.get(kind, [])]
    si = tui.menu(f'{head} — what kind of action belongs here?',
                  [v for v, _ in SUITS_VOCAB], [h for _, h in SUITS_VOCAB],
                  subtitle=f'{label} — {REACH[ri][0]}', multi=True, selected=pre)
    if si is None:
        return False

    # a control that mechanically nudges another one -- a trigger pushing past
    # a lever -- shows the neighbour's buttons in its own trace. Leave them
    # where they already are rather than quietly taking them.
    owned = {}
    for g in raw['group']:
        if g['kind'] == 'unknown':
            continue
        for b in all_of(g):
            owned[b] = g.get('label') or g['kind']
    stolen = {b: owned[b] for b in list(order) + list(transient) if b in owned}
    if stolen:
        order = [b for b in order if b not in stolen]
        transient = [b for b in transient if b not in stolen]
        if rest_contact in stolen:
            rest_contact = None
        tui.confirm(head,
                    ['These already belong to another control, so they stay'
                     ' there:', ''] +
                    [f'   button {b} -- {who}' for b, who in stolen.items()],
                    ['A trigger that pushes past a lever sees the lever in its',
                     'own trace. That does not make it part of the trigger.'],
                    default=True)
        if not order:
            return False

    entry = {'kind': kind, 'buttons': order, 'label': label,
             'reach': REACH[ri][0],
             'suits': [SUITS_VOCAB[i][0] for i in si], 'source': 'measured'}
    if dirs:
        key = {'trigger': 'stages', 'selector': 'positions'}.get(kind, 'dirs')
        entry[key] = dirs
    if push is not None:
        entry['push'] = push
    if rest_contact is not None:
        entry['rest_contact'] = rest_contact
    if cumulative:
        entry['cumulative'] = True
    if transient:
        entry['transient'] = transient
    if control_axes:
        entry['axes'] = control_axes
    raw['group'].append(entry)

    done = set(order) | set(transient)
    for extra in (push, rest_contact):
        if extra is not None:
            done.add(extra)
    unknown['buttons'] = [b for b in unknown['buttons'] if b not in done]
    if not unknown['buttons']:
        raw['group'].remove(unknown)
    return True


def capture_axis(tui, dev, fd):
    raw = dev._raw
    head = f'{dev.product} — axis'
    drain(fd)
    idx, travel = one_axis(tui, fd, head,
                           ['Move one axis end to end so it can be told apart.',
                            'Its resting behaviour is already measured.'])
    if idx is None:
        return False
    existing = next((a for a in raw.get('axis', []) if a['index'] == idx), None)
    facts = ''
    if existing:
        facts = (f'measured: {existing.get("hid", "?")} / '
                 f'{existing.get("evdev", "?")}, rests '
                 f'{existing.get("rest", "?")}   |   currently: '
                 f'{existing.get("label", "-")} ({existing.get("source")})')
    ki = tui.menu(f'{head} {idx} — what is it?', [k[1] for k in AXIS_KINDS],
                  [k[2] for k in AXIS_KINDS], subtitle=facts)
    if ki is None:
        return False
    if AXIS_KINDS[ki][0] in ('mini-stick-x', 'mini-stick-y'):
        if tui.confirm(
                f'{head} {idx} — part of a mini-stick?',
                ['A mini-stick is two axes and often a click.', '',
                 'Record it as one control rather than a lone axis?'],
                ['You will be asked for the click and the other axis.',
                 'Answering no just labels this axis on its own.']):
            return capture_ministick(
                tui, dev, fd, first_axis=idx,
                first_vertical=AXIS_KINDS[ki][0] == 'mini-stick-y')
    if AXIS_KINDS[ki][0] == 'dial':
        if tui.confirm(
                f'{head} {idx} — does it click?',
                ['A dial often presses in as well.', '',
                 'Record it as one control rather than a lone axis?'],
                ['You will be asked for the click.',
                 'Answering no just labels this axis on its own.']):
            return capture_ministick(tui, dev, fd, kind='dial', n_axes=1,
                                     first_axis=idx)

    label = tui.text(f'{head} {idx} — name it',
                     ['What you would call it looking at the device.'],
                     existing.get('label', '') if existing else '')
    if label is None:
        return False
    pre = [i for i, (v, _) in enumerate(AXIS_SUITS)
           if existing and v in existing.get('suits', [])]
    si = tui.menu(f'{head} {idx} — what belongs on it?',
                  [v for v, _ in AXIS_SUITS], [h for _, h in AXIS_SUITS],
                  subtitle=label, multi=True, selected=pre)
    if si is None:
        return False
    if existing is None:
        existing = {'index': idx}
        raw.setdefault('axis', []).append(existing)
    existing.update({'kind': AXIS_KINDS[ki][0], 'label': label,
                     'suits': [AXIS_SUITS[i][0] for i in si],
                     'source': 'measured'})
    if travel:
        existing['travel'] = travel
    existing.pop('note', None)
    return True


def reset_grouping(raw, n_buttons):
    """Throw the button grouping away and start over -- what a renumbering
    leaves you with, because the numbers in the file no longer point at the
    same physical controls."""
    keep = [g for g in raw['group'] if g['kind'] == 'switch-position']
    raw['group'] = keep + [{'kind': 'unknown', 'label': 'Not yet captured',
                            'source': 'unknown',
                            'buttons': sorted(set(range(n_buttons))
                                              - {b for g in keep
                                                 for b in g['buttons']})}]


def edit_axis(tui, dev, fd, ax):
    """Change what an axis is taken to be, without having to move it."""
    changed = False
    while True:
        facts = ' '.join(v for v in (ax.get('hid', ''), ax.get('rest', ''),
                                     ax.get('travel', '')) if v)
        descr = (f'axis {ax["index"]}  {facts}  '
                 f'{ax.get("label") or "-"}   [{ax.get("source")}]')
        fields = ['what it is', 'name', 'what belongs on it',
                  're-measure it (move it)', 'clear it', 'done']
        fhints = [['Mini-stick, lever, slider, dial, pedal...'],
                  ['What you would call it looking at the device.'],
                  ['Tick and untick with SPACE.'],
                  ['Moving it again refreshes whether it sweeps or steps.'],
                  ['Drops the interpretation. The measured facts -- HID kind,',
                   'resting behaviour -- stay, because those were not guessed.'],
                  ['Back to the device.']]
        fi = tui.menu(f'{dev.product} — edit axis', fields, fhints,
                      subtitle=descr, index=2)
        if fi is None or fi == 5:
            return changed

        if fi == 0:
            ki = tui.menu('What is it?', [k[1] for k in AXIS_KINDS],
                          [k[2] for k in AXIS_KINDS], subtitle=descr,
                          index=next((n for n, k in enumerate(AXIS_KINDS)
                                      if k[0] == ax.get('kind')), 0))
            if ki is not None:
                ax['kind'] = AXIS_KINDS[ki][0]
                ax['source'] = 'measured'
                changed = True
        elif fi == 1:
            v = tui.text('Name it', ['What you would call it looking at the'
                                     ' device.'], ax.get('label', ''))
            if v is not None:
                ax['label'] = v
                ax['source'] = 'measured'
                changed = True
        elif fi == 2:
            pre = [n for n, (v, _) in enumerate(AXIS_SUITS)
                   if v in ax.get('suits', [])]
            si = tui.menu('What belongs on it?', [v for v, _ in AXIS_SUITS],
                          [h for _, h in AXIS_SUITS], subtitle=descr,
                          multi=True, selected=pre)
            if si is not None:
                ax['suits'] = [AXIS_SUITS[n][0] for n in si]
                ax['source'] = 'measured'
                changed = True
        elif fi == 3:
            drain(fd)
            got, travel = one_axis(tui, fd, f'{dev.product} — axis',
                                   ['Move this one end to end.',
                                    f'Expecting axis {ax["index"]}.'])
            if got is None:
                continue
            if got != ax['index']:
                tui.confirm('Different axis',
                            [f'That was axis {got}, not {ax["index"]}.', '',
                             'Nothing changed.'], [], default=True)
                continue
            if travel:
                ax['travel'] = travel
                changed = True
        elif fi == 4:
            if tui.confirm('Clear it',
                           [descr, '', 'Drop what it is taken to be?'],
                           ['The HID kind and resting behaviour stay.'],
                           default=False):
                for k in ('kind', 'label', 'suits', 'note'):
                    ax.pop(k, None)
                ax['source'] = 'unknown'
                return True


def edit_group(tui, dev, fd):
    """Change a control that is already described, without pressing it again --
    ticking the wrong thing in a list should not cost a whole capture pass."""
    raw = dev._raw
    groups = [g for g in raw['group'] if g['kind'] != 'unknown']
    groups.sort(key=lambda g: min(g['buttons']) if g['buttons'] else 0)
    axes = sorted(raw.get('axis', []), key=lambda a: a['index'])
    if not groups and not axes:
        return False
    items = [f'{g["kind"]:16s} {str(all_of(g)):20s} {g.get("label", "")}'
             for g in groups]
    hints = [[f'reach: {g.get("reach", "-")}',
              f'suits: {", ".join(g.get("suits", [])) or "-"}',
              f'source: {g.get("source")}'] for g in groups]
    for a in axes:
        facts = ' '.join(v for v in (a.get('hid', ''), a.get('rest', ''),
                                     a.get('travel', '')) if v)
        items.append(f'{"axis " + str(a["index"]):16s} {facts:20s} '
                     f'{a.get("label") or "-"}')
        hints.append([f'suits: {", ".join(a.get("suits", [])) or "-"}',
                      f'source: {a.get("source")}',
                      'measured facts stay whatever you choose'])
    i = tui.menu(f'{dev.product} — edit what?', items, hints)
    if i is None:
        return False
    if i >= len(groups):
        return edit_axis(tui, dev, fd, axes[i - len(groups)])
    g = groups[i]
    changed = False

    while True:
        def descr():
            return (f'{g["kind"]}  {all_of(g)}  {g.get("label", "")}'
                    f'   [{", ".join(g.get("suits", [])) or "nothing"}]')

        fields = ['what it is', 'name', 'how you reach it',
                  'what belongs on it', 're-press the directions',
                  'delete it', 'done']
        fhints = [['Change the shape. Direction names are cleared with it.'],
                  ['What you would call it looking at the device.'],
                  ['Decides whether it can hold a reflex action.'],
                  ['Tick and untick with SPACE.'],
                  ['Only for a hat, a trigger or a multi-position switch.'],
                  ['The buttons go back to the unknown pile.'],
                  ['Back to the device.']]
        fi = tui.menu(f'{dev.product} — edit', fields, fhints,
                      subtitle=descr(), index=3)
        if fi is None or fi == 6:
            return changed

        if fi == 0:
            ki = tui.menu('What is it?', [k[1] for k in KINDS],
                          [k[3] for k in KINDS], subtitle=descr(),
                          index=next((n for n, k in enumerate(KINDS)
                                      if k[0] == g['kind']), 5))
            if ki is not None and KINDS[ki][0] != g['kind']:
                g['kind'] = KINDS[ki][0]
                g.pop('dirs', None)
                g.pop('stages', None)
                changed = True

        elif fi == 1:
            v = tui.text('Name it', ['What you would call it looking at the'
                                     ' device.'], g.get('label', ''))
            if v is not None:
                g['label'] = v
                changed = True

        elif fi == 2:
            ri = tui.menu('How do you reach it?', [r[0] for r in REACH],
                          [r[1] for r in REACH], subtitle=descr(),
                          index=next((n for n, r in enumerate(REACH)
                                      if r[0] == g.get('reach')), len(REACH) - 1))
            if ri is not None:
                g['reach'] = REACH[ri][0]
                changed = True

        elif fi == 3:
            pre = [n for n, (v, _) in enumerate(SUITS_VOCAB)
                   if v in g.get('suits', [])]
            si = tui.menu('What kind of action belongs here?',
                          [v for v, _ in SUITS_VOCAB],
                          [h for _, h in SUITS_VOCAB], subtitle=descr(),
                          multi=True, selected=pre)
            if si is not None:
                g['suits'] = [SUITS_VOCAB[n][0] for n in si]
                changed = True

        elif fi == 4:
            dirnames = next((k[2] for k in KINDS if k[0] == g['kind']), [])
            if not dirnames or len(g['buttons']) < 2:
                tui.confirm('Nothing to re-press',
                            [f'A {g["kind"]} has no directions to put in order.'],
                            [], default=True)
                continue
            want = dirnames[:len(g['buttons'])]
            picked = []
            drain(fd)
            for d in want:
                b = one_button(tui, fd, f'{dev.product} — {g.get("label", "")}',
                               f'press:  {d.upper()}',
                               ['Directions are physical, from your seat:',
                                'UP is away from you, toward the nose.',
                                'RETURN gives up and keeps the current order.'])
                if b is None:
                    picked = []
                    break
                picked.append(b)
            if picked and sorted(picked) == sorted(g['buttons']):
                g['buttons'] = picked
                g['stages' if g['kind'] == 'trigger' else 'dirs'] = want
                changed = True

        elif fi == 5:
            if tui.confirm('Delete it',
                           [descr(), '', 'Send these buttons back to unknown?'],
                           ['You can capture them again straight away.'],
                           default=False):
                raw['group'].remove(g)
                u = unknown_group(raw)
                u['buttons'] = sorted(set(u['buttons']) | set(all_of(g)))
                return True


def overview(tui, dev, js, probe=None):
    fd = os.open(js, os.O_RDONLY | os.O_NONBLOCK)
    dirty = False
    try:
        while True:
            btns, axes = dev.unknown()
            held = sorted(b for g in dev.groups('switch-position')
                          for b in g.buttons)
            lines = []
            for g in dev.groups(bindable=True):
                d = (f'  [{", ".join(g.dirs or g.stages)}]'
                     if (g.dirs or g.stages) else '')
                p = f' +push {g.push}' if g.push is not None else ''
                x = f' +axes {g.axes}' if g.axes else ''
                lines.append(f'  {g.kind:16s} {str(g.buttons):20s} '
                             f'{g.label}{d}{p}{x}')
            if dev.axes():
                lines.append('')
                for a in sorted(dev.axes(), key=lambda a: a.index):
                    owner = dev.axis_group(a.index)
                    own = f'  ({owner.label})' if owner else ''
                    mark = '' if a.source == 'measured' else f'  [{a.source}]'
                    lines.append(f'  axis {a.index:<4}{a.hid:<8}{a.rest:<9}'
                                 f'{a.travel:<9}{a.label or "-"}{own}{mark}')
            unwired = sorted(b for g in dev.groups('unwired')
                             for b in g.buttons)
            if unwired:
                lines.append(f'  nothing behind these: {unwired}')
            if btns:
                lines += ['', f'  still unknown: {btns}']
            if held:
                lines.append(f'  held at rest, leave alone: {held}')

            h = tui.scr.getmaxyx()[0]
            tui.scr.erase()
            for i, ln in enumerate(lines[:max(0, h - 8)]):
                tui._put(3 + i, 0, ln)
            tui._chrome(
                dev.product,
                f'{dev.n_buttons - len(btns)}/{dev.n_buttons} buttons described,'
                f' {dev.n_axes - len(axes)}/{dev.n_axes} axes'
                + ('    * unsaved' if dirty else ''),
                [], '',
                'RETURN = capture, E = edit, A = an axis, U = unwired, '
                'S = save, Q = quit')
            tui.scr.refresh()

            k = tui.key(0.5)
            if k in ('q', 'Q', 'esc'):
                return dirty
            if k in ('s', 'S'):
                if probe:
                    dev._raw['fingerprint'] = {
                        key: probe[key] for key in
                        ('buttons', 'axes', 'axmap', 'hid') if key in probe}
                write_device(dev)
                dirty = False
            elif k == 'enter':
                if capture_button(tui, dev, fd):
                    reconcile(dev._raw, dev.n_buttons)
                    dev.__init__(dev._raw, dev.path)   # refresh the query views
                    dirty = True
            elif k in ('u', 'U'):
                left, _ = dev.unknown()
                if left and tui.confirm(
                        f'{dev.product} — nothing behind them?',
                        [f'{len(left)} buttons are still unknown:', '',
                         f'   {left}', '',
                         'Record them as reported but not wired to anything?'],
                        ['The firmware allocates a fixed number of buttons, so'
                         ' some',
                         'indices have nothing physical behind them. This says'
                         ' you',
                         'looked -- which is not the same as not having looked'
                         ' yet.'],
                        default=False):
                    raw = dev._raw
                    raw['group'] = [g for g in raw['group']
                                    if g['kind'] != 'unknown']
                    raw['group'].append({
                        'kind': 'unwired', 'buttons': left,
                        'label': 'Reported by the firmware, nothing attached',
                        'source': 'measured'})
                    reconcile(dev._raw, dev.n_buttons)
                    dev.__init__(dev._raw, dev.path)
                    dirty = True
            elif k in ('e', 'E'):
                if edit_group(tui, dev, fd):
                    reconcile(dev._raw, dev.n_buttons)
                    dev.__init__(dev._raw, dev.path)
                    dirty = True
            elif k in ('a', 'A'):
                if capture_axis(tui, dev, fd):
                    reconcile(dev._raw, dev.n_buttons)
                    dev.__init__(dev._raw, dev.path)
                    dirty = True
    finally:
        os.close(fd)


def tui_main(scr, found):
    curses.curs_set(0)
    scr.nodelay(True)
    scr.keypad(True)
    try:
        curses.set_escdelay(50)
    except AttributeError:
        pass
    try:
        curses.start_color()
        curses.use_default_colors()
    except curses.error:
        pass
    tui = Tui(scr)

    while True:
        if len(found) == 1:
            m = found[0]
        else:
            items, hints = [], []
            for mm in found:
                d = mm.device
                b, _a = d.unknown()
                flag = '' if mm.ok else f'   [{mm.status}]'
                items.append(f'{d.product}  —  {d.n_buttons - len(b)}/'
                             f'{d.n_buttons} buttons described{flag}')
                hints.append([f'{mm.probe.get("usb")} / {mm.probe.get("serial")}',
                              f'{d.kind}, {d.hand} hand', mm.explain()])
            i = tui.menu('sim-device-map — which device?', items, hints,
                         quits=True)
            if i is None:
                return
            m = found[i]
        dev, js = m.device, m.js

        if m.status == devicemap.RECONFIGURED:
            if tui.confirm(
                    f'{dev.product} — new identity',
                    ['This device matches the map by shape but not by id:', '',
                     f'   in the file: {dev.usb} / {dev.serial}',
                     f'   plugged in:  {m.probe.get("usb")} / '
                     f'{m.probe.get("serial")}', '',
                     'Same hardware after a reconfiguration?'],
                    ['Saying yes keeps both ids, so either one is recognised.',
                     'The shape is unchanged, so the grouping still holds.']):
                dev.add_identity(m.probe)
                write_device(dev)
                m.status = devicemap.EXACT
        elif m.status == devicemap.DRIFT:
            diffs = dev.fingerprint_diff(m.probe)
            if tui.confirm(
                    f'{dev.product} — the shape changed',
                    ['Same device id, but the hardware reports something else:',
                     ''] + [f'   {line}' for line in diffs] +
                    ['', 'Throw the button grouping away and start over?'],
                    ['The numbers in the file may no longer point at the same',
                     'physical controls. Answering no keeps it -- then check',
                     'each hat before you trust it.'], default=False):
                reset_grouping(dev._raw, m.probe.get('buttons', dev.n_buttons))
                dev.__init__(dev._raw, dev.path)

        dirty = overview(tui, dev, js, m.probe)
        if dirty and tui.confirm(
                'Unsaved changes',
                [f'{dev.product} has changes that are not written.', '',
                 'Write them to the device file?'],
                ['The file is validated before it replaces the old one.']):
            write_device(dev)
        if len(found) == 1:
            return


def watch_raw(matches):
    """Live press AND release. capture.py only ever looks at presses, so a
    control that also emits something when you let go is invisible to it."""
    fds = {}
    for m in matches:
        fd = os.open(m.js, os.O_RDONLY | os.O_NONBLOCK)
        drain(fd)
        fds[fd] = m.device.product
    print('working the controls prints every event; Ctrl-C to stop\n')
    start = time.monotonic()
    held = {}
    try:
        while True:
            ready, _, _ = select.select(list(fds), [], [], 0.2)
            for fd in ready:
                for typ, num, val in _events(fd):
                    t = time.monotonic() - start
                    who = fds[fd]
                    if typ & JS_EVENT_BUTTON:
                        if val:
                            held[(fd, num)] = t
                            print(f'{t:7.2f}  {who:26s} button {num:3d}  DOWN')
                        else:
                            down = held.pop((fd, num), None)
                            ms = f'  (held {1000 * (t - down):.0f} ms)' if down else ''
                            print(f'{t:7.2f}  {who:26s} button {num:3d}  up{ms}')
                    elif typ & JS_EVENT_AXIS:
                        print(f'{t:7.2f}  {who:26s} axis   {num:3d}  {val:6d}')
    except KeyboardInterrupt:
        print()
    finally:
        for fd in fds:
            os.close(fd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true',
                    help='show what is known and exit, without the TUI')
    ap.add_argument('--raw', action='store_true',
                    help='print every button and axis event live, press and '
                         'release, until Ctrl-C -- for working out what a '
                         'control actually does')
    args = ap.parse_args()

    connected = devicemap.find_connected()
    found = [m for m in connected if m.device]
    for m in connected:
        if m.device is None:
            print(f'{m.js}  {m.probe.get("usb") or "?"}  — not in the map; '
                  f'add a device file')
    if not found:
        raise SystemExit('no mapped device connected')

    if args.raw:
        return watch_raw(found)

    if args.list:
        for m in found:
            js, dev = m.js, m.device
            if not m.ok:
                print(f'   [{m.status}] {m.explain()}')
            btns, axes = dev.unknown()
            print(f'{js}  {dev.product}')
            print(f'    {dev.n_buttons - len(btns)}/{dev.n_buttons} buttons '
                  f'described, {dev.n_axes - len(axes)}/{dev.n_axes} axes')
            for g in dev.groups(bindable=True):
                d = (f'  [{", ".join(g.dirs or g.stages)}]'
                     if (g.dirs or g.stages) else '')
                p = f' +push {g.push}' if g.push is not None else ''
                x = f' +axes {g.axes}' if g.axes else ''
                print(f'      {g.kind:16s} {str(g.buttons):22s} '
                      f'{g.label}{d}{p}{x}')
            if btns:
                print(f'      {"unknown":16s} {btns}')
        return

    curses.wrapper(tui_main, found)


if __name__ == '__main__':
    main()
