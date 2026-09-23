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
import sys
import time
import tomllib
from dataclasses import dataclass

import devicemap
import questions
import screens
import tui as ui

JS_EVENT_BUTTON, JS_EVENT_AXIS, JS_EVENT_INIT = 0x01, 0x02, 0x80

# slug, menu label, direction names, the rows shown while the cursor is on it
#: The shapes on offer, out of `questions.toml`. Held there rather than
#: here because the wizard that replaces these flows asks about them from
#: the same list, and two copies of a vocabulary is one copy that drifts.
SHEET = questions.read()
KINDS = [(k['name'], k['says'], list(k.get('dirs') or []), list(k['hint']))
         for k in SHEET.vocabulary['kind']]

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

def drain(fd):
    """Swallow the synthetic initial-state burst the kernel sends on open."""
    while select.select([fd], [], [], 0.15)[0]:
        try:
            if not os.read(fd, 8 * 128):
                return          # end of the stream, not a pause in it
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


def collect_buttons(tui, fd, title, help_lines, tail='', says='',
                    wanted=None, right=''):
    """Buttons pressed, in first-press order, until RETURN.

    Also reports which are still closed at that moment: a switch that stays put
    leaves one held, a sprung one leaves none, and that is the whole difference
    between two shapes that look identical on the way in.
    """
    seen, held = [], set()
    while True:
        tui.screen(title,
                   [('plain', says or 'press every part of ONE control,'
                                    ' then RETURN')]
                   + ([('plain', '')] if seen else [])
                   + [_pressed(b, wanted) for b in seen]
                   + ui.aside_of(help_lines),
                   ('↵ done', 'ESC cancel'),
                   tail or (f'looking for js {wanted}'
                            if wanted is not None
                            else ui.plural(len(seen), 'button') if seen
                            else ''),
                   right=right)
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


def _pressed(button, wanted):
    """One button you just pressed, and whether it is the one you picked.

    Picking `js 19` off the list tells you a number and nothing about
    which piece of plastic it is. Saying so as you press is the only way
    to find out short of pressing everything and counting.
    """
    if wanted is None:
        return ('measured', f'button {button}')
    said = f'js {button:<4}'
    return (('measured', f'{said}  that one') if button == wanted
            else ('meta', f'{said}  different button'))


def one_button(tui, fd, title, prompt, help_lines):
    """Wait for a single press. RETURN skips and returns None."""
    while True:
        tui.screen(title, [('plain', prompt)] + ui.aside_of(help_lines),
                   ('press it', '↵ skip'))
        if select.select([fd], [], [], 0.05)[0]:
            for typ, num, val in _events(fd):
                if typ & JS_EVENT_BUTTON and val:
                    return num
        k = tui.key(0)
        if k in ('enter', 'esc'):
            return None


#: A button that closes within this long of an axis moving is very likely
#: the same physical control -- the end of a lever's travel, or a hat that
#: clicks. Measured by hand on the VMAX: a deliberate second press never
#: landed this close, and a lever's own switch never landed further.
TOGETHER = 0.35

#: Two axes reporting within this of each other, over and over, are one
#: control -- or two clamped together, which is the same thing to anybody
#: laying out bindings.
LOCKSTEP = 0.02


@dataclass
class Moved:
    """Two things that keep happening at the same moment.

    `kind` is what sort of coincidence it is: a button closing while an
    axis travels, or two axes reporting the same value. `times` is how
    often, because once is a coincidence and twenty times is a lever.
    """
    kind: str                   # 'contact' or 'axes'
    a: int                      # the button, or the lower axis
    b: int                      # the axis
    times: int


def what_moved_together(events):
    """[Moved] -- what the trace says is one piece of plastic.

    `events` are `(seconds, kind, number, value)` in the order they
    happened. The map answers "what is this button" well and "what else
    moves when I touch it" not at all, and that gap has cost real time:
    a trim axis bound to a throttle lever that travels under the same
    hand trims the aircraft on every power change.
    """
    contact, locked = {}, {}
    axes = [(t, num, val) for t, kind, num, val in events if kind == 'axis']
    for t, kind, num, val in events:
        if kind == 'button' and val == 1:
            for t2, n2, _v in axes:
                if abs(t2 - t) <= TOGETHER:
                    contact[(num, n2)] = contact.get((num, n2), 0) + 1
    for i, (t, num, val) in enumerate(axes):
        for t2, n2, v2 in axes[i + 1:]:
            if t2 - t > LOCKSTEP:
                break
            if n2 != num and v2 == val:
                key = (min(num, n2), max(num, n2))
                locked[key] = locked.get(key, 0) + 1
    out = ([Moved('contact', a, b, n) for (a, b), n in contact.items()]
           + [Moved('axes', a, b, n) for (a, b), n in locked.items()])
    return sorted(out, key=lambda m: (-m.times, m.kind, m.a, m.b))


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
        best = max(moved, key=lambda ax: moved[ax]) if moved else None
        travel = classify_travel(seen.get(best, [])) if best is not None else ''
        said = [('plain', 'move ONE axis through its full travel,'
                          ' then RETURN'), ('plain', '')]
        if best is not None:
            said.append(('measured',
                         f'axis {best}   (travel seen: {moved[best]})'))
            if travel:
                said.append(('meta', 'reports a continuous sweep'
                             if travel == 'analog' else
                             'reports only its extremes -- a hat on an axis'))
        tui.screen(title, said + ui.aside_of(help_lines),
                   ('↵ accept', 'ESC cancel'))
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
    pad = max(pad, len(key) + 1)
    if '\n' in val or len(val) > 86:
        body = val.replace('\\', '\\\\').replace('"""', '\\"\\"\\"')
        return f'{key:<{pad}}= """{body}"""'
    return f'{key:<{pad}}= "{esc(val)}"'


def emit_list(key, vals, pad=7):
    pad = max(pad, len(key) + 1)
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
        out.append(emit_raw('index', str(a['index'])))
        for k in ('evdev', 'hid', 'rest', 'travel', 'kind', 'label'):
            if a.get(k):
                out.append(emit_str(k, a[k]))
        # What `w` on the list measured about this axis moving with
        # another: not re-derivable from a capture, and cheap to carry.
        if a.get('moves_with'):
            out.append(emit_list('moves_with', list(a['moves_with'])))
        if a.get('coupling'):
            out.append(emit_str('coupling', a['coupling']))
        for k in ('range', 'noise'):
            if a.get(k) is not None:
                out.append(emit_raw(k, str(a[k])))
        out.append(emit_str('source', a.get('source', 'unknown')))
        if a.get('note'):
            out.append(emit_str('note', a['note']))

    out.append('\n# ------------------------------------------------------------------ buttons')
    # Named before anything is emitted, and put back on the device, so
    # the next flow to touch a group sees the ids this write gave them.
    groups = sorted(raw.get('group', []),
                    key=lambda g: (g['kind'] == 'unknown',
                                   min(all_of(g) or [0])))
    raw['group'] = devicemap.name_ids(groups)
    for g in groups:
        out.append('\n[[group]]')
        out.append(emit_str('kind', g['kind']))
        if g.get('id'):
            out.append(emit_str('id', g['id']))
        if g.get('cumulative'):
            out.append(emit_raw('cumulative', 'true'))
        if g.get('axes'):
            out.append(emit_list('axes', list(g['axes'])))
        for k in ('label', 'rest'):
            if g.get(k):
                out.append(emit_str(k, g[k]))
        for k in ('blind_distinct', 'accident_risk'):
            if g.get(k):
                out.append(emit_str(k, g[k]))
        for k in ('hold_ok', 'rapid_ok', 'modifier_ok'):
            if g.get(k) is not None:
                out.append(emit_raw(k, 'true' if g[k] else 'false'))
        if g.get('note'):
            out.append(emit_str('note', g['note']))
        out.append(emit_str('source', g.get('source', 'unknown')))
        if g.get('states'):
            out.extend(emit_states(g['states']))

    tmp = dev.path + '.tmp'
    open(tmp, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    with open(tmp, 'rb') as f:              # never leave a broken file behind
        tomllib.load(f)
    os.replace(tmp, dev.path)


# -------------------------------------------------------------------- flow

# -------------------------------------------------------------------- flow --

def write_profile(prof):
    """Write a rig back out, the same way a device file is written.

    Validated by reading the temporary file before it replaces the real
    one, so a crash halfway through leaves the rig you had.

    Everything before the first `name =` is kept: it is prose somebody
    wrote about this desk and nothing regenerates it.
    """
    out = []
    try:
        with open(prof.path) as fh:
            head = fh.read()
        cut = head.index('\nname')
        out.append(head[:cut].rstrip('\n'))
    except (OSError, ValueError):
        pass
    out.append('' if not out else '')
    out.append(emit_str('name', prof.name, 4))
    for said in prof.devices:
        out.append('\n[[device]]')
        for k in ('slug', 'role', 'hand'):
            if said.get(k):
                out.append(emit_str(k, said[k], 4))
        if said.get('leaving_home_releases_flight'):
            out.append(emit_raw('leaving_home_releases_flight', 'true', 4))
        walked = said.get('rounds') or []
        if walked:
            out.append(emit_raw('rounds', '[', 4))
            for lvl, finger in walked:
                out.append(f'    [{emit_val(lvl)}, {emit_val(finger)}],')
            out.append(']')
        access = {c: spots for c, spots in (said.get('access') or {}).items()
                  if spots}
        if not access:
            continue
        out.append('\n[device.access]')
        wide = max(len(c) for c in access)
        for ctrl in sorted(access):
            rows = [_spot_said(sp) for sp in access[ctrl]]
            if len(rows) == 1:
                out.append(f'{ctrl:<{wide}} = [{rows[0]}]')
            else:
                out.append(f'{ctrl:<{wide}} = [')
                out.extend(f'    {r},' for r in rows)
                out.append(']')

    text = '\n'.join(out).lstrip('\n') + '\n'
    tmp = prof.path + '.tmp'
    with open(tmp, 'w') as fh:
        fh.write(text)
    with open(tmp, 'rb') as fh:
        tomllib.load(fh)
    os.replace(tmp, prof.path)


def _spot_said(spot):
    """One way of reaching a control, as an inline table."""
    got = spot if isinstance(spot, dict) else {
        'part': spot.part, 'level': spot.level, 'finger': spot.finger}
    bits = [f'part = {emit_val(got["part"])}',
            f'level = {emit_val(got["level"])}']
    if got.get('finger'):
        bits.append(f'finger = {emit_val(got["finger"])}')
    return '{ ' + ', '.join(bits) + ' }'


def unknown_group(raw):
    """The bucket of not-yet-captured buttons, created if it was emptied."""
    g = next((x for x in raw['group'] if x['kind'] == 'unknown'), None)
    if g is None:
        g = {'kind': 'unknown', 'states': [], 'label': 'Not yet captured',
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
                 'source': 'unknown', 'states': []}
            raw['group'].append(u)
        set_buttons(u, missing)
    elif u is not None:
        raw['group'].remove(u)
    return missing


def all_of(g):
    """`Group.all_buttons` over the raw dict, before it is parsed."""
    return [s['button'] for s in g.get('states') or []
            if s.get('button') is not None]


def buttons_of(g):
    """A raw group's position buttons, in press order, whatever shape the
    dict is in. The contacts it also owns are in `all_of`."""
    return [st['button'] for st in g.get('states') or []
            if not st.get('role') and st.get('button') is not None]


def set_buttons(g, buttons, names=()):
    """Give a raw group these positions in place, keeping its contacts.

    `names` are a hat's directions or a trigger's detents. A control whose
    positions have no names -- a plain button, the uncaptured bucket --
    passes none.
    """
    kept = [st for st in g.get('states') or [] if st.get('role')]
    g['states'] = states_of(
        g['kind'], buttons, names,
        directional=g['kind'] not in ('trigger', 'selector')) + kept
    return g


def emit_states(states, pad=7):
    """One position per line, its columns lined up with the next one's.

    A position is four facts at most, so it reads as a row. The same list
    with one key per line is forty lines for a hat that clicks, and nothing
    in it is worth a line of its own.
    """
    rows = []
    for st in states:
        bits = []
        if st.get('name'):
            bits.append(('name', emit_val(st['name'])))
        if st.get('button') is not None:
            bits.append(('button', str(st['button'])))
        for k in ('direction', 'role'):
            if st.get(k):
                bits.append((k, emit_val(st[k])))
        if st.get('latching'):
            bits.append(('latching', 'true'))
        if st.get('emits_signal') is False:
            bits.append(('emits_signal', 'false'))
        rows.append(bits)
    wide = {}
    for bits in rows:
        for k, v in bits:
            wide[k] = max(wide.get(k, 0), len(v))
    out = [emit_raw('states', '[', pad)]
    for bits in rows:
        said = ' '.join(f'{k} = {v}' if i == len(bits) - 1
                        else f'{k} = {v + ",":<{wide[k] + 1}}'
                        for i, (k, v) in enumerate(bits))
        out.append(f'    {{ {said} }},')
    out.append(']')
    return out


def emit_raw(key, text, pad=7):
    """A key and an already-formatted value, in the same column as the rest."""
    return f'{key:<{max(pad, len(key) + 1)}}= {text}'


def emit_val(v):
    """A TOML scalar, quoted if it is a string."""
    return f'"{esc(v)}"' if isinstance(v, str) else str(v)


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
        said = [('plain', 'start at one end, sweep to the other,'
                          ' then RETURN'), ('plain', '')]
        said += [('measured', f'position {i + 1}:  button {b}')
                 for i, b in enumerate(got['order'])]
        if got['order'] and not got['exclusive']:
            said.append(('unset',
                         'more than one closed at once -- not a selector?'))
        tui.screen(title, said + ui.aside_of(
            ['The position you start on never sends a press: its contact is',
             'already closed and only shows itself by opening. That is what',
             'puts it first.']),
            ('↵ done', 'ESC cancel'), ui.plural(len(events), 'event'))
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
        said = [('plain', 'pull it all the way and let go, then RETURN'),
                ('plain', '')]
        said += [('measured', f'stage {i + 1}:       button {b}')
                 for i, b in enumerate(got['stages'])]
        if got['rest'] is not None:
            said.append(('guessed', f'rest contact:  button {got["rest"]}'
                                    '   (closed when untouched)'))
        said += [('guessed', f'passing:       button {b}'
                             '   (fires again on the way out)')
                 for b in got['transient']]
        tui.screen(title, said + ui.aside_of(
            ['Stages that nest are cumulative: pulling through fires',
             'everything bound up to that stage. A rest or passing contact',
             'is recorded but never offered for binding.']),
            ('↵ done', 'ESC cancel'), ui.plural(len(events), 'event'))

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


def ask_one(tui, fd, run, ask, head, note='', wanted=None):
    """One question on the screen. The answer, `ui.BACK`, or None to give up.

    Every branch here is a widget; which one is `ask.how`, out of the
    descriptor. What used to decide this was the shape of the surrounding
    `if`, which is why editing needed a second copy of all of it.
    """
    width = tui.scr.getmaxyx()[1] - 8
    trail = screens.trail_tree(run.trail(), width)
    aside = screens.note_lines(ask)
    title = f'{head} — {ask.says}'

    if ask.how == 'collect':
        drain(fd)
        seen, held = collect_buttons(tui, fd, head, aside, wanted=wanted)
        if seen is None:
            return None
        got = (seen, held)
        return got if questions.answered(ask, got) else ui.BACK

    if ask.how in ('pick', 'tick'):
        picks = SHEET.choices(ask)
        got = tui.menu(title, [c['says'] for c in picks],
                       [list(c.get('hint') or []) + aside for c in picks],
                       multi=(ask.how == 'tick'), under=trail, back=True,
                       tail=note)
        if got is None or got is ui.BACK:
            return got
        return ([picks[i]['name'] for i in got] if ask.how == 'tick'
                else picks[got]['name'])

    if ask.how == 'name':
        return tui.ask(title, aside, _suggest(run))

    if ask.how == 'press':
        drain(fd)
        return one_button(tui, fd, head, ask.says, aside)

    if ask.how == 'watch':
        drain(fd)
        watch = observe_trigger if ask.id == 'pull' else observe_selector
        return watch(tui, fd, head)

    if ask.how == 'sort':
        return press_in_order(tui, fd, run, head, aside)

    raise ValueError(f'{ask.id}: no widget draws {ask.how!r}')


def press_in_order(tui, fd, run, head, aside):
    """Put a control's directions in the order its buttons are in.

    The buttons were collected in whatever order you happened to press
    them, and a hat's directions are only worth anything against the right
    ones.
    """
    want = list(run.said.get('dirs') or [])
    seen, _held = run.given['buttons']
    picked = []
    drain(fd)
    for way in want[:len(seen)]:
        b = one_button(tui, fd, head, f'press:  {way.upper()}',
                       aside + [f'{len(picked)} of {len(want)} so far.'])
        if b is None:
            return ui.BACK
        picked.append(b)
    if sorted(picked) != sorted(seen[:len(picked)]):
        tui.confirm('Different buttons',
                    ['That was not the same set you pressed before, so the',
                     'order is left as it was.'], [], default=True)
        return list(seen)
    return picked


def _suggest(run):
    """A name to start from, out of what the shape is called."""
    entry = SHEET.choice(run.by_id['kind'], run.given.get('kind', ''))
    return (entry['says'].split(' (')[0].title() if entry else '')


def ask_reach(tui, fd, dev, prof):
    """Reach, measured by reaching. True if the rig moved.

    A list of the rounds rather than fifteen screens in a row, because a
    row of steps says neither how far in you are nor which ones are worth
    doing -- and most of them, on most devices, find nothing.
    """
    said = prof.entry(dev.slug)
    if said is None:
        return False
    ask = SHEET.of(questions.DEVICE)[0]
    levels = SHEET.vocabulary['level']
    note = screens.note_lines(ask)
    moved, at = False, 1
    while True:
        rounds = screens.reach_rounds(dev, prof, levels)
        rows = screens.reach_rows(rounds)
        done = sum(1 for r in rounds if r.done)
        what, at = tui.browse(
            f'Reach — {dev.product}', rows,
            lambda n: screens.reach_side(dev, rounds, n, note),
            keys=('↑↓ move', '↵ measure', 'ESC done'),
            right=f'{done} of {len(rounds)} done',
            index=at, aside='this round',
            # The rows are not the rounds -- three of them are postures --
            # so counting rows here would disagree with the count on the
            # other half of the frame. Which round it is, the cursor says.
            count=lambda _n: '')
        if what is None:
            if done == len(rounds):
                _hands_off(tui, dev, said)
                write_profile(prof)
            return moved
        one = screens._round_at(rounds, at)
        if one is None:
            # A heading is not a round. Rather than a key that does
            # nothing on a third of the rows, it goes where it says.
            at = screens.next_round_at(rounds, at)
        elif _one_round(tui, fd, dev, prof, said, one):
            moved = True


def _one_round(tui, fd, dev, prof, said, one):
    """Walk one round and write what it found. False if it was cancelled."""
    drain(fd)
    title, aside, says = screens.round_prompt(one)
    seen, _held = collect_buttons(tui, fd, title, aside, says=says)
    if seen is None:
        return False
    access = said.setdefault('access', {})
    # This round's earlier answers go first: doing it again replaces what
    # it said rather than adding to it.
    for spots in access.values():
        spots[:] = [sp for sp in spots
                    if not (sp.get('level') == one.level['name']
                            and sp.get('finger') == one.finger)]
    for b in seen:
        g = dev.group_of(b)
        if g is not None and g.id:
            access.setdefault(g.id, []).append(
                {'part': _part_of(dev, one.level['name']),
                 'level': one.level['name'], 'finger': one.finger})
    walked = said.setdefault('rounds', [])
    if [one.level['name'], one.finger] not in walked:
        walked.append([one.level['name'], one.finger])
    write_profile(prof)
    return True


def _hands_off(tui, dev, said):
    """Once every round is walked, what none of them reached is off it.

    Only then. Half the rounds say nothing about a control except that it
    has not come up yet, and writing that down as OFF would be recording
    an answer nobody gave.

    Said out loud, because it is the one answer on this screen you never
    gave by pressing something: it is what the rounds add up to, and it
    lands on whatever you did not press in any of them.
    """
    access = said.setdefault('access', {})
    left = [g for g in dev.groups(bindable=True)
            if g.id and not access.get(g.id)]
    for g in left:
        access[g.id] = [{'part': 'panel', 'level': 'OFF'}]
    if left:
        tui.popup(
            'Every finger done',
            [('plain', f'You never pressed {ui.plural(len(left), "control")}'
                       ' from any grip, so reaching them means taking your'
                       ' hand off the device. That is now what they say.'),
             ('plain', '')]
            + [('meta', f'  {g.label or g.kind}') for g in left])


def reach_from(dev, pressed):
    """What a set of rounds amounts to: {control id: [spot]}.

    `pressed` is `[(level, finger, buttons)]`, one entry per round.

    Whatever was never pressed comes out as OFF. That is not a gap in the
    answers -- a control you did not reach from anywhere on the device is a
    control you take your hand off for, and saying nothing about it would
    leave it looking unmeasured instead.
    """
    got = {}
    for level, finger, seen in pressed:
        for b in seen:
            g = dev.group_of(b)
            if g is not None and g.id:
                got.setdefault(g.id, []).append(
                    {'part': _part_of(dev, level), 'level': level,
                     'finger': finger})
    for g in dev.groups(bindable=True):
        if g.id and g.id not in got:
            got[g.id] = [{'part': 'panel', 'level': 'OFF'}]
    return got


def _part_of(dev, level):
    """Which part of the rig a hand is on at this level."""
    return dev.kind if level in devicemap.GRIPPED else f'{dev.kind}_base'


def ask_facts(tui, fd, dev):
    """The five ergonomic facts, as a list rather than a menu. True if
    anything moved.

    Per question and not per control, for the same reason the reach rounds
    are: these are comparative, and twenty-six controls times five
    questions is a hundred and thirty screens nobody would finish.
    """
    asks = SHEET.of(questions.ALL)
    moved, at = False, 0
    while True:
        rows = screens.fact_rows(dev, asks)
        done = sum(1 for tone, _t in rows if tone == screens.TONE['measured'])
        what, at = tui.browse(
            f'Facts — {dev.product}', rows,
            lambda n: screens.fact_side(dev, asks, n),
            keys=('↑↓ move', '↵ answer this one', 'ESC done'),
            right=f'{done} of {len(asks)} answered', index=at)
        if what is None:
            return moved
        moved = ask_all(tui, fd, dev, asks[at]) or moved


def ask_all(tui, fd, dev, ask):
    """One question down every control at once. True if anything moved.

    The hardware is in your hands, so it is the input: press a control on
    the device and its answer changes. Twenty-six rows of arrow keys is
    the same work with the device sitting there unused.
    """
    controls = [g for g in dev.groups(bindable=True) if g.id]
    if not controls:
        return False
    picks = SHEET.choices(ask)
    moved, at = False, 0

    def poll():
        nonlocal moved
        if not select.select([fd], [], [], 0)[0]:
            return None
        for typ, num, val in _events(fd):
            if typ & JS_EVENT_BUTTON and val:
                g = dev.group_of(num)
                if g is not None and g in controls:
                    _step(dev, g, ask, picks)
                    moved = True
                    return controls.index(g)
        return None

    while True:
        rows = screens.answer_rows(dev, ask, controls)
        told = sum(1 for g in controls if g.told(ask.sets) == 'measured')
        what, at = tui.browse(
            screens.caption(ask), rows,
            lambda n: screens.answer_side(dev, ask, controls, n),
            keys=('press a control', 'SPACE answers', '↵ done'),
            right=f'{told} of {len(controls)} answered',
            index=at, takes=(' ',), poll=poll)
        if what in (None, 'enter'):
            return moved
        if what == ' ':
            _step(dev, controls[at], ask, picks)
            moved = True


def _step(dev, group, ask, picks):
    """Move a control's answer on by one, and off the end back to none.

    One gesture for both shapes of question: a yes/no has two answers to
    walk round and a graded one has three. Round the end is no answer at
    all, because the alternative is that a control you touched by mistake
    can never go back to unanswered -- and unanswered is the one state
    nothing else can put back.
    """
    names = [c['name'] for c in picks] if picks else [True, False]
    now = group.fact(ask.sets)
    at = names.index(now) if now in names else -1
    _set_fact(dev, group, ask.sets,
              names[at + 1] if at + 1 < len(names) else None)


def _set_fact(dev, group, field, value):
    """Record an ergonomic fact against a control, in the file and in hand."""
    for raw in dev._raw['group']:
        if raw.get('id') == group.id:
            raw[field] = value
    setattr(group, field, value)


def walk_control(tui, fd, dev, group=None, wanted=None):
    """Ask about one control, from nothing or from what it already says.

    Returns the finished `Run`, or None if it was given up on. Editing is
    this same walk with answers already in it, which is the whole reason
    the order lives in a descriptor.
    """
    run = questions.Run(SHEET, given=_already(group) if group else None)
    head = dev.product if group is None else f'{dev.product} — {group.label}'
    at, note = None, ''
    if run.done:
        # Already answered for. Walking it again would ask nothing and hand
        # back what it already had, so the useful thing is to let you say
        # which of the answers was wrong.
        at = _pick_from_trail(tui, run, group.label if group else '')
        if at is None:
            return None
    while True:
        ask = run.by_id[at] if at else run.next()
        if ask is None:
            return run
        got = ask_one(tui, fd, run, ask, head, note, wanted)
        note = ''
        if got is None:
            return None
        if got is ui.BACK:
            at = _before(run, ask)
            continue
        gone = run.revise(ask, got)
        at = None
        if gone:
            # Said on the next question rather than in a box of its own: it
            # is a consequence of what you just did, not an event.
            note = screens.dropped_said(gone)


def _pick_from_trail(tui, run, called):
    """Which answer to change, for a control that has them all already."""
    said = run.trail()
    n = tui.choose(f'Edit {called}' if called else 'Edit control',
                   screens.trail_tree(said, 56, lead=''),
                   keys=('↑↓ move', '↵ change it', 'ESC back'))
    return None if n is None else said[n][0].id


def _before(run, ask):
    """The question to step back into, or the one you are on if it is first."""
    done = [i for i in run.order if i != ask.id]
    return done[-1] if done else ask.id


def _already(group):
    """What a captured control has already answered.

    Including the observations. A trigger's stored states ARE what watching
    the pull produced -- stages, a rest contact, contacts that fire on the
    way past -- so reading them back is the difference between opening a
    described trigger and being made to pull it again.
    """
    seen = [st.button for st in group.states if st.button is not None]
    said = {'buttons': (seen, set()), 'kind': group.kind}
    if group.label:
        said['name'] = group.label
    if group.kind in questions.CLICKS:
        # Recorded even when there is none: "it does not click" is an
        # answer, and a control missing it is a control the walk thinks it
        # has not finished asking about.
        said['click'] = group.push
    if group.kind == 'trigger':
        said['pull'] = {'stages': list(group.buttons),
                        'rest': group.contact('rest'),
                        'transient': list(group.transient),
                        'cumulative': bool(group.cumulative)}
        if group.contact('rest') is not None:
            said['returns'] = 'yes'
    elif group.kind == 'selector':
        said['sweep'] = {'order': list(group.buttons), 'exclusive': True,
                         'names': list(group.names)}
    elif group.names:
        # A shape that knows its own directions needs no telling. One that
        # does not -- a rocker could be any of three pairs -- has to have
        # the answer read back out of what it was called, or the question
        # never applies and the names go with it.
        said['which_way'] = _which_way(group.names)
        if not said['which_way']:
            del said['which_way']
        said['order'] = list(group.buttons)
    return said


def _which_way(names):
    """The vocabulary entry whose directions are these, if there is one."""
    return next((c['name'] for c in SHEET.vocabulary.get('axis', ())
                 if list(c.get('dirs') or ()) == list(names)), '')


def build_group(run, keep=None):
    """A raw group dict out of what a run answered.

    This is where `sets` in the descriptor becomes a field in the file.
    The positions go through `states_of`, which is also what a reorder
    goes through, so one place knows what a group looks like on disk.
    """
    said = run.given
    seen, _held = said.get('buttons', ([], set()))
    # The click is not one of the places you can put the control, and a
    # dial or a mini-stick has nothing else: collecting picks it up with
    # the rest, and leaving it here makes it its own position as well.
    seen = [b for b in seen if b != said.get('click')]
    entry = {'kind': said['kind'], 'label': said.get('name', ''),
             'source': 'measured'}
    places = list(said.get('order') or seen)
    names = list(run.said.get('dirs') or [])[:len(places)]
    directional = bool(names)
    contacts = []
    if said.get('click') is not None:
        contacts.append(('push', said['click']))
    pull = said.get('pull')
    if pull:
        places = list(pull['stages'])
        names = ['first', 'second', 'third'][:len(places)]
        directional = False
        if pull.get('cumulative'):
            entry['cumulative'] = True
        if pull.get('rest') is not None and said.get('returns') == 'yes':
            contacts.append(('rest', pull['rest']))
        contacts += [('transient', b) for b in pull.get('transient') or []]
    sweep = said.get('sweep')
    if sweep:
        places = list(sweep['order'])
        # A sweep does not name its own positions; a capture already on
        # file does, and re-reading one must not rename what it found.
        names = list(sweep.get('names') or [
            f'position {n + 1}' for n in range(len(places))])
        directional = False
    entry['states'] = states_of(entry['kind'], places, names, directional,
                                contacts)
    if keep is not None:
        # A control keeps its name through a recapture, because a profile
        # points at it by that name and the buttons are what moved. Its
        # axes come along for the same reason: nothing here asked about
        # them, so nothing here may drop them.
        if keep.id:
            entry['id'] = keep.id
        if keep.axes:
            entry['axes'] = list(keep.axes)
    return entry


#: What each contact is called where it is not a position of the control.
CONTACT_SAID = {'push': 'push', 'rest': 'rest', 'travel': 'travel',
                'transient': 'passing'}


def states_of(kind, places, names=(), directional=False, contacts=()):
    """The positions of a control, as the file has them.

    Positions first and in press order, then whatever the control also
    closes: a click, a rest contact, a travel contact, the ones it brushes
    on the way. That order is what a consumer walking the list sees.

    Only what is not the default goes in. A state carrying every field it
    could have is unreadable, and a default written down is a default
    somebody has to keep in step by hand.
    """
    latching = kind in devicemap.LATCHING
    out = []
    for n, b in enumerate(places):
        name = names[n] if n < len(names) else ''
        out.append({'button': b}
                   | ({'name': name, 'direction': name} if name and directional
                      else {'name': name} if name else {})
                   | ({'latching': True} if latching else {}))
    for role, b in contacts:
        out.append({'name': CONTACT_SAID[role], 'button': b, 'role': role}
                   | ({'latching': True} if role in ('rest', 'travel')
                      else {}))
    return out


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

    label = tui.ask(f'{head} — name it',
                     ['What you would call it looking at the device.'],
                     'Dial' if kind == 'dial' else 'Mini-stick')
    if label is None:
        return False

    entry = {'kind': kind, 'buttons': [], 'label': label,
             'axes': axes, 'source': 'measured'}
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
        set_buttons(u, [b for b in buttons_of(u) if b != click])
        if not buttons_of(u):
            raw['group'].remove(u)
    for i in axes:
        ax = next((x for x in raw.get('axis', []) if x['index'] == i), None)
        if ax is not None and ax.get('source') != 'measured':
            ax['source'] = 'measured'
            ax.pop('note', None)
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

    label = tui.ask(f'{head} {idx} — name it',
                     ['What you would call it looking at the device.'],
                     existing.get('label', '') if existing else '')
    if label is None:
        return False
    if existing is None:
        existing = {'index': idx}
        raw.setdefault('axis', []).append(existing)
    existing.update({'kind': AXIS_KINDS[ki][0], 'label': label,
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
                            'states': [{'button': b} for b in
                                       sorted(set(range(n_buttons))
                                              - {b for g in keep
                                                 for b in all_of(g)})]}]


def overview(tui, dev, js, probe=None):
    """Every control on one device, and how far each has got.

    The list IS the progress: what somebody answered for, what is standing
    on what its shape usually is, and what nobody has placed yet. Pressing
    RETURN on a row walks its questions, and that walk is the same one a
    fresh capture takes -- there is no separate edit screen any more.
    """
    fd = os.open(js, os.O_RDONLY | os.O_NONBLOCK)
    dirty, sel = False, 0
    try:
        while True:
            rows = screens.control_rows(dev)
            btns, axes = dev.unknown()
            left = sum(1 for r in rows if r.tone != 'measured')
            got = tui.choose(
                dev.product, [(r.tone, r.text) for r in rows],
                index=min(sel, max(0, len(rows) - 1)), full=True,
                keys=screens.sill_keys(), takes=screens.takes(),
                poll=_watch(dev, fd, rows), corner='pressed',
                right=f'{len(rows) - left}/{len(rows)} done · '
                      f'{dev.n_axes - len(axes)}/{dev.n_axes} axes'
                      + (' · unsaved' if dirty else ''),
                tail='? help')

            if got is None or got in ('q', 'Q'):
                return dirty
            if got == '?':
                tui.popup('help', screens.key_help())
                continue
            if got in ('w', 'W'):
                if watch(tui, dev, fd):
                    dirty = True
                continue
            if got in ('s', 'S'):
                if probe:
                    dev._raw['fingerprint'] = {
                        k: probe[k] for k in ('buttons', 'axes', 'axmap', 'hid')
                        if k in probe}
                write_device(dev)
                dirty = False
            elif got in ('r', 'R'):
                prof = devicemap.profile()
                if prof is None:
                    tui.confirm('No rig on file',
                                ['Reach is a fact about the desk, so it has',
                                 'nowhere to go without one.'], [],
                                default=True)
                elif ask_reach(tui, fd, dev, prof):
                    _reload(dev)
            elif got in ('f', 'F'):
                dirty = ask_facts(tui, fd, dev) or dirty
            elif got in ('a', 'A'):
                dirty = capture_axis(tui, dev, fd) or dirty
                _reload(dev)
            elif got in ('u', 'U'):
                dirty = _mark_unwired(tui, dev, btns) or dirty
                _reload(dev)
            elif got in ('n', 'N') or isinstance(got, int):
                sel = got if isinstance(got, int) else sel
                row = rows[got] if isinstance(got, int) else None
                old = row.group if row is not None else None
                if old is not None and not old.bindable:
                    continue
                run = walk_control(tui, fd, dev, old,
                                   row.button if row is not None else None)
                if run is None or not run.done:
                    continue
                if not _replace(dev, old, build_group(run, old)):
                    continue
                _reload(dev)
                dirty = True
    finally:
        os.close(fd)


def watch(tui, dev, fd):
    """Touch one thing at a time and see everything it fires.

    The map answers "what is this button" and says nothing about what
    else moves with it. That gap cost real time twice: a trim axis went
    on a throttle lever that travels under the same hand, so every power
    change trimmed the aircraft, and a paddle and a grip lever sit in the
    file as two controls and may be one piece of plastic.

    True when it wrote something. What it can write is a coupling between
    two axes; a button that closes during a travel is a fact about one
    control, and the place to fix that is the control.
    """
    events, rest = start_trace(fd)
    start = time.time()
    while True:
        for typ, num, val in _events(fd):
            add_event(events, rest, time.time() - start, typ, num, val)
        moved = what_moved_together(events)
        h, _w = tui.scr.getmaxyx()
        rows = screens.trace_rows(dev, events, room=max(1, h - 4))
        tui.screen(f'Watch — {dev.product}',
                   rows or [('meta', 'Touch one control at a time.')],
                   ('\u21b5 done', 'ESC cancel'),
                   ui.plural(len(events), 'event'), full=True)
        # Over the oldest rows, which is where the trace's least useful
        # end now is, and in the same place every frame.
        tui.corner('moved together', screens.together_rows(dev, moved))
        tui.scr.refresh()
        k = tui.key(0.05)
        if k == 'esc':
            return False
        if k == 'enter':
            return _record_couplings(tui, dev, moved)


#: How far an axis has to travel before it counts as moving. A stick at
#: rest jitters by a few hundred either way.
AXIS_MOVED = 3000


def axes_at_rest(fd):
    """Where each axis is sitting, from the burst the driver sends on open.

    `drain` throws that burst away, which is what you want when you are
    waiting for somebody to press something. Here it is exactly wrong: a
    lever parked at one end reads its first real report as a full-scale
    move, and the trace opens with something that did not happen.

    Read raw rather than through `_events`, which drops the opening state
    on the floor for the same good reason every other flow wants it gone.
    """
    rest = {}
    while select.select([fd], [], [], 0.15)[0]:
        try:
            data = os.read(fd, 8 * 128)
        except BlockingIOError:
            break
        if not data:            # end of the stream, not a pause in it
            break
        for i in range(0, len(data), 8):
            _t, val, typ, num = struct.unpack('<IhBB', data[i:i + 8])
            if typ & JS_EVENT_AXIS:
                rest[num] = val
    return rest


def start_trace(fd):
    """An empty trace, and where the axes are sitting as it opens.

    One thing rather than two lines in the loop above, because the two
    have to agree: a trace that starts without the rest positions opens
    with a full-scale move on every axis parked away from centre, and
    `drain` -- which every other flow calls here -- throws exactly those
    positions away.
    """
    return [], axes_at_rest(fd)


def add_event(events, rest, now, typ, num, val):
    """Put one joystick event into a trace, or drop it. True if kept.

    `rest` is where each axis was last seen. An axis that has not
    travelled since is dropped, because a trace of a stick jittering at
    rest is a trace of nothing with the real events pushed off the top.
    """
    if typ & JS_EVENT_AXIS:
        if abs(val - rest.get(num, 0)) < AXIS_MOVED:
            return False
        rest[num] = val
        events.append((now, 'axis', num, val))
        return True
    if typ & JS_EVENT_BUTTON:
        events.append((now, 'button', num, val))
        return True
    return False

#: What two axes that move as one can be to each other. `switchable` is
#: the VMAX's throttle levers: clamped together by a catch on the device,
#: so the pair is a choice you made rather than how it is built.
COUPLINGS = ('switchable', 'always')


def _record_couplings(tui, dev, moved):
    """Write down the axis pairs the trace found. True if anything moved."""
    pairs = [m for m in moved if m.kind == 'axes']
    if not pairs:
        return False
    wrote = False
    for m in pairs:
        said = tui.menu(
            f'axis {m.a} and axis {m.b} move as one',
            [f'{c} — {_COUPLING_SAID[c]}' for c in COUPLINGS],
            [[_COUPLING_SAID[c]] for c in COUPLINGS],
            subtitle=f'{screens._thing_said(dev, "axis", m.a)}\n'
                     f'{screens._thing_said(dev, "axis", m.b)}')
        if said is None:
            continue
        for one, other in ((m.a, m.b), (m.b, m.a)):
            raw = next((a for a in dev._raw.get('axis', [])
                        if a.get('index') == one), None)
            if raw is None:
                continue
            with_ = sorted(set(raw.get('moves_with') or []) | {other})
            raw['moves_with'] = with_
            raw['coupling'] = COUPLINGS[said]
            ax = dev.axis(one)
            if ax is not None:
                ax.moves_with, ax.coupling = with_, COUPLINGS[said]
            wrote = True
    return wrote


_COUPLING_SAID = {
    'switchable': 'a catch on the device clamps them; you can unclamp it',
    'always': 'they are built as one and never move apart',
}


def _watch(dev, fd, rows):
    """Watch the hardware while the list is up: what was that button?

    The list answers "which button is this row". This answers the same
    question from the other end, which is the one you actually have -- a
    piece of plastic under your thumb and no idea what it is called.
    """
    def poll():
        if not select.select([fd], [], [], 0)[0]:
            return None
        for typ, num, val in _events(fd):
            if typ & JS_EVENT_BUTTON and val:
                return (screens.row_of(rows, dev, num),
                        screens.what_is(dev, num))
        return None
    return poll


def _reload(dev):
    """Re-derive the typed view after the raw one moved under it."""
    reconcile(dev._raw, dev.n_buttons)
    dev.__init__(dev._raw, dev.path)
    dev.under(devicemap.profile())


def _replace(dev, old, entry):
    """Put a described control in, and take out whatever it displaced.

    False when the entry owns nothing at all: no buttons, no contacts, no
    axes. Nothing downstream can do anything with one, and it sits in the
    list as a row with no name and no way to give it one.
    """
    if not all_of(entry) and not entry.get('axes'):
        return False
    raw = dev._raw
    claimed = set(all_of(entry))
    # Noted before anything is taken out, because the thing being looked
    # for is exactly the thing about to go.
    where = next((n for n, g in enumerate(raw['group'])
                  if entry.get('id') and g.get('id') == entry.get('id')),
                 None)
    for g in list(raw['group']):
        if g is not entry and (claimed & set(all_of(g))
                               or (entry.get('id')
                                   and g.get('id') == entry.get('id'))):
            if g['kind'] == 'unknown':
                set_buttons(g, [b for b in buttons_of(g) if b not in claimed])
            else:
                raw['group'].remove(g)
    # Back where it was rather than at the end: the file is sorted on the
    # way out, but the list you are looking at is not, and a control that
    # jumps to the bottom when you describe it loses your place.
    raw['group'].insert(len(raw['group']) if where is None
                        else min(where, len(raw['group'])), entry)
    return True


def _mark_unwired(tui, dev, btns):
    """Say that the firmware reports these and nothing is behind them."""
    if not btns:
        return False
    if not tui.confirm('Nothing behind them',
                       [f'Mark {btns} as reported but not wired?'],
                       ['They stop being offered as free buttons.'],
                       default=False):
        return False
    dev._raw['group'].append(
        {'kind': 'unwired', 'source': 'measured',
         'states': states_of('unwired', list(btns)),
         'label': 'Reported by the firmware, nothing attached'})
    return True


#: What one device can be to a rig. `role` is what it is FOR on this desk,
#: which is not always what it is: a second throttle can be the collective.
ROLES_ON_A_DESK = ('stick', 'throttle', 'pedals', 'panel', 'collective')

HANDS = ('left', 'right')


def edit_rig(tui, prof):
    """Which hand is on what, for every device this desk names.

    Nothing else asks these. `hand` decides whether two controls can be
    worked at once, and until somebody says it every pair on the desk
    reads as a pair of hands that might be the same one.
    """
    at, moved = 0, False
    while True:
        devs = [d for d in devicemap.load_all(bare=True)
                if prof.entry(d.slug) is not None]
        if not devs:
            tui.popup(f'{prof.name} has no devices',
                      [('plain', 'A desk names the devices on it. This one'
                                 ' names none, or names captures that are'
                                 ' not on file.')])
            return moved
        what, at = tui.browse(
            f'{prof.name} — which hand is on what',
            screens.rig_rows(prof, devs),
            lambda n: screens.rig_side(prof, devs, n),
            keys=('↑↓ move', '↵ change it', 'ESC back'),
            index=min(at, len(devs) - 1))
        if what is None:
            return moved
        if _say_where_it_sits(tui, prof, devs[at]):
            moved = True


def _say_where_it_sits(tui, prof, dev):
    """Hand, role, and whether letting go of it drops the aircraft."""
    said = prof.entry(dev.slug)
    if said is None:
        return False
    hand = tui.menu(f'{dev.product} — which hand?', list(HANDS),
                    [[f'It sits under your {h} hand.'] for h in HANDS],
                    index=HANDS.index(said['hand']) if said.get('hand')
                    in HANDS else 0)
    if hand is None:
        return False
    said['hand'] = HANDS[hand]
    role = tui.menu(f'{dev.product} — what is it for?',
                    list(ROLES_ON_A_DESK),
                    [[f'On this desk it is the {r}.']
                     for r in ROLES_ON_A_DESK],
                    index=(ROLES_ON_A_DESK.index(said['role'])
                           if said.get('role') in ROLES_ON_A_DESK else 0))
    if role is not None:
        said['role'] = ROLES_ON_A_DESK[role]
    said['leaving_home_releases_flight'] = bool(tui.confirm(
        f'{dev.product} — does letting go of it matter?',
        ['Does taking your hand off this one stop you flying?'],
        ['True of a stick you are holding the aircraft with, and false of'
         ' a throttle you can leave where it is.',
         'It is why a control you have to let go of to reach is further'
         ' away than one you only stretch for.'],
        default=said.get('leaving_home_releases_flight', False)))
    write_profile(prof)
    return True


def pick_desk(tui, here=None):
    """Which desk this is, and the chance to change what it says.

    Returns the rig to read devices under, or None if you left without
    choosing one. A rig is not a preference stored somewhere: it is the
    answer to "where am I sitting", which nothing but you can know, so it
    is asked once a session and never guessed.
    """
    at = 0
    while True:
        rigs = devicemap.load_profiles()
        if not rigs:
            if not tui.confirm('No desk on file',
                               ['Nothing says where your hardware sits.'],
                               ['A desk says which hand is on what, and'
                                ' what each control is within reach of.',
                                'Without one nothing can be measured about'
                                ' reach, and every control reads as being'
                                ' nowhere.']):
                return None
            if _new_desk(tui) is None:
                return None
            continue
        have = devicemap.load_all(bare=True)
        what, at = tui.browse(
            'Which desk is this?',
            screens.profile_rows(rigs, here),
            lambda n: screens.profile_side(rigs, n, here, have),
            keys=screens.desk_keys(), index=min(at, len(rigs) - 1),
            takes=screens.desk_takes(), tail='? help')
        if what is None:
            return here
        if what == 'enter':
            return rigs[at]
        if what == '?':
            tui.popup('help', screens.desk_help())
        elif what in ('n', 'N'):
            _new_desk(tui)
        elif what in ('r', 'R'):
            _rename_desk(tui, rigs[at])
        elif what in ('d', 'D'):
            _delete_desk(tui, rigs[at], here)
        elif what in ('e', 'E'):
            edit_rig(tui, rigs[at])


def _new_desk(tui):
    """Start a desk with nothing on it. The rig, or None if you backed out."""
    name = tui.ask('New desk', ['What is this one called? "Biurko",'
                                ' "Fotel", whatever tells them apart.'])
    if not name:
        return None
    path = os.path.join(devicemap.PROFILES, devicemap.slug(name) + '.toml')
    if os.path.exists(path):
        tui.popup('That name is taken',
                  [('plain', f'{os.path.basename(path)} is already on file.')])
        return None
    prof = devicemap.Profile({'name': name, 'device': []}, path)
    write_profile(prof)
    return prof


def _rename_desk(tui, prof):
    """Rename a desk in place. The file keeps its own name."""
    name = tui.ask('Rename', [f'Now called {prof.name}.'], default=prof.name)
    if not name or name == prof.name:
        return False
    prof.name = name
    write_profile(prof)
    return True


def _delete_desk(tui, prof, here):
    """Delete a desk and the file under it. True if it went."""
    said = [f'{prof.name} — {ui.plural(len(prof.devices), "device")}']
    measured = sum(len(d.get('rounds') or []) for d in prof.devices)
    if measured:
        said.append(f'{ui.plural(measured, "measured reach")} on it')
    if prof is here:
        said.append('This is the desk you are working at.')
    if not tui.confirm(f'Delete {prof.name}?', said,
                       ['The file goes with it. What a control IS stays in'
                        ' its capture; where it ended up does not.'],
                       default=False):
        return False
    try:
        os.remove(prof.path)
    except OSError as e:
        tui.popup('It is still there', [('plain', str(e))])
        return False
    return True


def tui_main(scr, rig):
    tui = ui.setup(scr)
    # Asked before anything is read, because what a device is under one
    # desk it is not under another: the hand, the roles, and every reach
    # already measured all come from here.
    rig = pick_desk(tui, rig)
    if rig is None:
        return
    found = [m for m in devicemap.find_connected(rig) if m.device]
    if not found:
        tui.popup('Nothing connected that the map knows',
                  [('plain', 'Plug something in, or capture it first.')])
        return

    while True:
        if len(found) == 1:
            m = found[0]
        else:
            items = [t for _tone, t in screens.found_rows(found)]
            hints = [screens.found_hints(mm) for mm in found]
            i = tui.menu('sim-device-map — which device?', items, hints,
                         quits=True)
            # Not `is None`: a menu that ticks several answers with a
            # list, and one row is what this screen means by an answer.
            if not isinstance(i, int):
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

    # No desk over it: whether a joystick has a capture on file is true
    # at every desk or at none, and asking which desk this is belongs on
    # a screen -- where there is somebody to answer.
    connected = devicemap.find_connected(bare=True)
    found = [m for m in connected if m.device]
    for m in connected:
        if m.device is None:
            print(f'{m.js}  {m.probe.get("usb") or "?"}  — not in the map; '
                  f'add a device file')
    if not found and (args.raw or args.list):
        raise SystemExit('no mapped device connected')

    if args.raw:
        return watch_raw(found)

    if args.list:
        # Under a desk when one can be settled, because how far away a
        # control is is a fact about the desk and not about the device.
        rig = devicemap.profile(strict=False)
        if rig is not None:
            found = [m for m in devicemap.find_connected(rig=rig) if m.device]
        elif devicemap.load_profiles():
            print('# more than one desk on file, so reach is left out;'
                  ' SIM_DEVICE_PROFILE=<name> to read under one')
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
                t = f'  tier {g.tier}' if g.tier is not None else ''
                print(f'      {g.kind:16s} {str(g.buttons):22s} '
                      f'{g.label}{d}{p}{x}{t}')
            if btns:
                print(f'      {"unknown":16s} {btns}')
        return

    # Which desk, and the devices under it, are both settled inside: the
    # question needs a screen, and the answer changes what is read.
    curses.wrapper(tui_main, devicemap.profile(strict=False))


if __name__ == '__main__':
    main()
