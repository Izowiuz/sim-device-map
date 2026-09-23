"""Hardware nobody plugged in.

The dicts here are the on-disk schema, and they are handed to the real
`devicemap.Device` rather than to a stand-in. A stub class agrees with
whatever the test expects; the real one disagrees the moment the schema moves
under it, which is the only reason to have these at all.

Event lists are the shape `analyse_selector` and `analyse_trigger` read:
`(t, button, down)`, seconds and a bool. `press`/`release` build them so a
test reads as the gesture it describes rather than as a list of triples.
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import devicemap                                            # noqa: E402


#: The desk the tests work at. Not one off the disk: `profiles/` holds
#: whatever rigs the person running these happens to own, and a suite that
#: reads those fails the day they add a second desk -- which is a fact
#: about their room, not about this code.
RIG = {'name': 'a desk in a test', 'device': []}


def rig(*devices):
    """A `Profile` naming these devices, each under a hand.

    `devices` are `(slug, hand)`, or a `Device` for the plain case of
    "it is on the desk and nothing more is said".
    """
    said = []
    for d in devices:
        slug, hand = d if isinstance(d, tuple) else (d.slug, 'left')
        said.append({'slug': slug, 'hand': hand})
    return devicemap.Profile(dict(RIG, device=said), '<test-desk>')


def devices(rig=None):
    """Every captured device, under a desk the test owns.

    Deliberately not `devicemap.load_all()`: that asks which desk this
    is, and the answer is on the disk of whoever is running the tests.
    """
    return devicemap.load_all(bare=rig is None, rig=rig)


def group(kind, buttons=(), names=(), dirs=(), stages=(), push=None,
          rest_contact=None, travel_contact=None, transient=(), **kw):
    """One raw `[[group]]` table.

    `buttons` are the positions and the rest are the contacts a control
    also closes, spelled out here rather than in a nest of dicts: a test
    saying `push=9` reads as the thing it is describing.

    `dirs` names positions that point somewhere, `stages` and `names` ones
    that do not. The difference is a `direction` on each state, and it is
    the only reason the fixture asks which of the three you mean.
    """
    latching = kind in devicemap.LATCHING
    names = list(names or dirs or stages)
    states = []
    for n, b in enumerate(buttons):
        said = names[n] if n < len(names) else ''
        states.append({'button': b}
                      | ({'name': said, 'direction': said} if said and dirs
                         else {'name': said} if said else {})
                      | ({'latching': True} if latching else {}))
    for role, b in (('push', push), ('rest', rest_contact),
                    ('travel', travel_contact)):
        if b is not None:
            states.append({'name': role, 'button': b, 'role': role}
                          | ({'latching': True} if role != 'push' else {}))
    for b in transient:
        states.append({'name': 'passing', 'button': b, 'role': 'transient'})
    g = {'kind': kind, 'states': states}
    g.update({k: v for k, v in kw.items() if v is not None})
    g.setdefault('source', 'measured')
    return g


def control(kind, buttons=(), **kw):
    """A parsed `Group`."""
    return devicemap.Group(**group(kind, buttons, **kw))


def axis(index, kind='lever', **kw):
    """One raw `[[axis]]` table."""
    a = {'index': index, 'kind': kind}
    a.update({k: v for k, v in kw.items() if v is not None})
    a.setdefault('source', 'measured')
    return a


def raw(kind='stick', groups=(), axes=(), slug=None, product=None,
        hand='', usb='3344:0001', serial='FAKE01', evdev=None,
        buttons=None, fingerprint=None):
    """The dict a capture file parses into."""
    slug = slug or f'fake-{kind}'
    every = [b for g in groups for b in _claimed(g)]
    return {
        'device': {'slug': slug, 'product': product or f'Fake {kind}',
                   'vendor': 'Fake', 'kind': kind, 'hand': hand,
                   'buttons': buttons if buttons is not None
                              else 1 + max(every or [-1]),
                   'axes': len(axes)},
        'identity': [{'usb': usb, 'serial': serial,
                      'evdev': evdev or f'Fake {kind}',
                      'first_seen': '2026-01-01'}],
        'fingerprint': dict(fingerprint or {}),
        'axis': [dict(a) for a in axes],
        'group': [dict(g) for g in groups],
    }


def device(kind='stick', groups=(), axes=(), path=None, **kw):
    """A `devicemap.Device` with no hardware behind it."""
    data = raw(kind, groups, axes, **kw)
    return devicemap.Device(data, path or f'<fake:{data["device"]["slug"]}>')


def _claimed(g):
    """Every button a raw group mentions, whatever the field is called.

    Deliberately not `capture.all_of` or `Group.all_buttons`: this is the
    fixture working out how big a device has to be, and it must not inherit
    the disagreement between those two that `test_bookkeeping` is about.
    """
    return [st['button'] for st in g.get('states') or []
            if st.get('button') is not None]


# ----------------------------------------------------------------- screen --

class Screen:
    """A grid that records what was drawn on it.

    The one place a fake terminal earns its keep. Everything else about a
    screen here is a pure function returning strings, but "a box clears
    what was under it" is not something a string can be asked about -- and
    a box drawn over a wider one used to leave that one's edges around it,
    which reads as two dialogs open at once.
    """

    def __init__(self, h=14, w=78, keys=()):
        self.h, self.w = h, w
        #: Keystrokes to hand back, one per `getch`, then nothing forever.
        #: A screen that never answers leaves an input loop spinning.
        self.keys = list(keys)
        self.erase()

    def getmaxyx(self):
        return self.h, self.w

    def erase(self):
        self.rows = [[' '] * self.w for _ in range(self.h)]

    def refresh(self):
        pass

    def getch(self) -> int:
        return self.keys.pop(0) if self.keys else -1

    def addstr(self, y, x, text, attr=0):
        for i, ch in enumerate(text):
            if 0 <= y < self.h and 0 <= x + i < self.w:
                self.rows[y][x + i] = ch

    def text(self):
        return '\n'.join(''.join(r).rstrip() for r in self.rows).strip()


# --------------------------------------------------------------- gestures --

def press(t, button):
    return (t, button, True)


def release(t, button):
    return (t, button, False)


def squeeze(*buttons, start=1.0, step=0.1):
    """Press them in order, then let go in the reverse order.

    A trigger's stages nest: the second detent closes while the first is still
    held, and opens before it. That nesting is what `analyse_trigger` reads to
    tell a staged trigger from several buttons under one finger.
    """
    out, t = [], start
    for b in buttons:
        out.append(press(t, b))
        t += step
    for b in reversed(buttons):
        out.append(release(t, b))
        t += step
    return out


def sweep(*buttons, start=1.0, step=0.1):
    """A rotary selector turned end to end.

    The position it starts on is already closed, so it never sends a press --
    it opens as the knob leaves it. That opening is the only evidence of where
    the sweep began, and `analyse_selector` is built entirely around it.
    """
    out, t = [], start
    out.append(release(t, buttons[0]))
    t += step
    for b in buttons[1:]:
        out.append(press(t, b))
        t += step
        if b is not buttons[-1]:
            out.append(release(t, b))
            t += step
    return out


# ------------------------------------------------------------------ probe --

def probed(dev=None, js='/dev/input/js9', usb=None, serial=None,
           buttons=None, axes=None, axmap=None, hid=None, evdev=None):
    """What `devicemap.probe()` hands back for a connected device.

    Defaults are read off `dev` when one is given, so a test that wants an
    EXACT match says `probed(dev)` and a test that wants a mismatch says which
    field moved.
    """
    ident = (dev.identities[0] if dev is not None and dev.identities else {})
    fp = (dev.fingerprint if dev is not None else {}) or {}
    return {
        'js': js,
        'usb': (usb if usb is not None else ident.get('usb', '')).lower(),
        'serial': serial if serial is not None else ident.get('serial', ''),
        'buttons': buttons if buttons is not None
                   else fp.get('buttons', dev.n_buttons if dev else 0),
        'axes': axes if axes is not None
                else fp.get('axes', dev.n_axes if dev else 0),
        'axmap': list(axmap if axmap is not None else fp.get('axmap', [])),
        'hid': list(hid if hid is not None else fp.get('hid', [])),
        'evdev': evdev if evdev is not None else ident.get('evdev', ''),
    }


# ------------------------------------------------------------------ files --

def on_disk(data, name='fake-device.toml'):
    """`(Device, tempdir)` for a raw dict written out as a real file.

    The writer replaces the file it was given and validates by reading it
    back, so anything testing it needs a path that exists. The caller cleans
    the directory up.
    """
    box = tempfile.TemporaryDirectory()
    path = os.path.join(box.name, name)
    with open(path, 'w') as fh:
        fh.write('# a capture file\n')
    return devicemap.Device(data, path), box
