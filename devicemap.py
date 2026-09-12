#!/usr/bin/env python3
"""Read the device map: what each control on a piece of flight hardware is.

    import devicemap
    dev = devicemap.by_usb('3344:43e8')
    dev.groups('hat4')            # every four-way hat, in press order
    dev.axes(suits='view')        # axes that suit head-look
    dev.unknown()                 # what still needs capturing

Matching is deliberately two-layered, because VIRPIL's own configuration tool
can change a device's USB id, its serial and its name in one go:

- `[[identity]]` -- USB id + serial. A device may carry several, because a
  reconfiguration mints a new one and the old one is worth keeping.
- `[fingerprint]` -- button count, axis count, axis map and HID usages. This
  survives an identity change, so the same physical hardware is still
  recognisable afterwards.

Never match on the evdev name: VIRPIL bakes the firmware build date into it.

The two layers disagreeing is itself the useful signal. A known identity with a
changed fingerprint means the BUTTONS MAY HAVE BEEN RENUMBERED, so the grouping
in the file is suspect and wants re-capturing -- a silent re-link would be worse
than no match at all.
"""

import glob
import os
import tomllib
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
#: captures/<manufacturer>/<device>.toml -- the manufacturer is the directory,
#: so the `slug` inside does not have to repeat it and a second brand of pedals
#: does not land in the same pile.
CAPTURES = os.path.join(HERE, 'captures')

#: How well a connected device lines up with its file.
EXACT = 'exact'                 # identity and fingerprint both agree
DRIFT = 'identity-drift'        # same identity, different shape: data suspect
RECONFIGURED = 'reconfigured'   # same shape, new identity: probably the VPC tool
UNKNOWN = 'unknown'             # nothing in the map looks like it

#: `source` values, weakest last.  Consumers should treat anything below
#: "measured" as a hypothesis that a capture pass can overturn.
TRUST = ('measured', 'inferred', 'unknown')


@dataclass
class Axis:
    index: int
    evdev: str = ''
    hid: str = ''
    rest: str = ''          # centred | min | max | mid
    travel: str = ''        # analog | stepped -- a hat wired to an axis steps
    kind: str = ''
    label: str = ''
    suits: list = field(default_factory=list)
    note: str = ''
    source: str = 'unknown'

    @property
    def centring(self):
        return self.rest == 'centred'

    @property
    def proportional(self):
        """False for a mini-hat wired to an axis: it reports its extremes and
        nothing in between, so aiming or head movement gets three positions
        instead of a sweep."""
        return self.travel != 'stepped'

    @property
    def safe_for_absolute(self):
        """True when resting position reads as zero, so an axis where zero
        means 'off' (brakes, zoom) will not be stuck on at rest."""
        return self.rest == 'min'


@dataclass
class Group:
    kind: str               # hat4 hat8 trigger switch2 switch3 button paddle
    buttons: list           # ordered: hats by dirs, triggers by stages
    label: str = ''
    dirs: list = field(default_factory=list)
    stages: list = field(default_factory=list)
    positions: list = field(default_factory=list)  # a latch: one per position
    push: int = None        # a hat that also clicks
    cumulative: bool = False  # a deeper stage keeps the shallower ones held
    rest_contact: int = None  # closed while the control is UNTOUCHED
    transient: list = field(default_factory=list)  # pulses DURING the travel
    axes: list = field(default_factory=list)  # axes belonging to this control
    reach: str = ''
    rest: str = ''
    suits: list = field(default_factory=list)
    note: str = ''
    source: str = 'unknown'

    @property
    def all_buttons(self):
        """Every button this control owns, bindable or not."""
        out = list(self.buttons)
        if self.push is not None:
            out.append(self.push)
        if self.rest_contact is not None:
            out.append(self.rest_contact)
        out.extend(self.transient)
        return out

    @property
    def bindable_buttons(self):
        """What may safely carry an action.

        A rest contact is closed whenever the control is untouched, so anything
        bound to it runs all the time except while you are using the control.
        A transient contact closes partway through the travel and so fires
        again on the way back out -- a weapon bound there goes off twice per
        squeeze. Both are left out here and listed in `all_buttons`, so
        coverage still adds up and a consumer that wants one must ask for it.
        """
        if self.kind in ('unknown', 'switch-position', 'unwired'):
            return []
        out = list(self.buttons)
        if self.push is not None:
            out.append(self.push)
        return out

    @property
    def bindable(self):
        """A button held down at rest fires continuously; never bind it. Nor
        one the firmware reports with nothing physically behind it."""
        return self.kind not in ('unknown', 'switch-position', 'unwired')

    def direction(self, button):
        """Which way this button points, for a hat or a staged trigger."""
        if self.push is not None and button == self.push:
            return 'push'
        if self.rest_contact is not None and button == self.rest_contact:
            return 'rest contact (inverted)'
        if button in self.transient:
            return 'transient (fires both ways)'
        names = self.dirs or self.stages or self.positions
        if not names or button not in self.buttons:
            return ''
        i = self.buttons.index(button)
        return names[i] if i < len(names) else ''


class Device:
    def __init__(self, data, path):
        self.path = path
        self._raw = data
        d = data['device']
        self.slug = d['slug']
        self.product = d['product']
        self.vendor = d.get('vendor', '')
        self.kind = d.get('kind', '')
        self.hand = d.get('hand', '')
        self.n_buttons = d.get('buttons', 0)
        self.n_axes = d.get('axes', 0)
        ident = data.get('identity', {})
        if isinstance(ident, dict):         # the original single-table form
            ident = [ident] if ident else []
        self.identities = [dict(i) for i in ident]
        first = self.identities[0] if self.identities else {}
        self.usb = first.get('usb', '').lower()
        self.serial = first.get('serial', '')
        self.evdev_name = first.get('evdev', '')
        self.game_ids = first.get('games', {})
        self.fingerprint = data.get('fingerprint', {})
        self._axes = [Axis(**a) for a in data.get('axis', [])]
        self._groups = [Group(**g) for g in data.get('group', [])]

    # ---- queries ----

    def axes(self, kind=None, suits=None, source=None):
        out = self._axes
        if kind:
            out = [a for a in out if a.kind == kind]
        if suits:
            out = [a for a in out if suits in a.suits]
        if source:
            out = [a for a in out if a.source == source]
        return out

    def axis(self, index):
        return next((a for a in self._axes if a.index == index), None)

    def axis_group(self, index):
        """The control an axis belongs to, when it is part of one -- a
        mini-stick is two axes and a click, not three unrelated things."""
        return next((g for g in self._groups if index in g.axes), None)

    def groups(self, kind=None, suits=None, bindable=None):
        out = self._groups
        if kind:
            out = [g for g in out if g.kind == kind]
        if suits:
            out = [g for g in out if suits in g.suits]
        if bindable is not None:
            out = [g for g in out if g.bindable == bindable]
        return out

    def group_of(self, button):
        return next((g for g in self._groups if button in g.all_buttons), None)

    def button_label(self, button):
        g = self.group_of(button)
        if not g:
            return f'button {button}'
        d = g.direction(button)
        return f'{g.label} — {d}' if d else g.label

    def unknown(self):
        """Controls still to capture: (unmapped buttons, unnamed axes)."""
        btns = sorted(b for g in self.groups('unknown') for b in g.all_buttons)
        axes = [a for a in self._axes if a.source == 'unknown']
        return btns, axes

    def game_id(self, game):
        for i in self.identities:
            if game in i.get('games', {}):
                return i['games'][game]
        return None

    # ---- matching ----

    def matches_identity(self, probe):
        for i in self.identities:
            if (i.get('usb', '').lower() == (probe.get('usb') or '').lower()
                    and i.get('serial', '') == (probe.get('serial') or '')):
                return True
        return False

    def matches_fingerprint(self, probe):
        f = self.fingerprint
        if not f:
            return None                     # nothing recorded, cannot say
        return (f.get('buttons') == probe.get('buttons')
                and f.get('axes') == probe.get('axes')
                and list(f.get('axmap', [])) == list(probe.get('axmap', []))
                and list(f.get('hid', [])) == list(probe.get('hid', [])))

    def fingerprint_diff(self, probe):
        out = []
        f = self.fingerprint
        for k in ('buttons', 'axes'):
            if f.get(k) != probe.get(k):
                out.append(f'{k}: {f.get(k)} -> {probe.get(k)}')
        for k in ('axmap', 'hid'):
            if list(f.get(k, [])) != list(probe.get(k, [])):
                out.append(f'{k}: {list(f.get(k, []))} -> {list(probe.get(k, []))}')
        return out

    def add_identity(self, probe):
        self.identities.append({'usb': probe.get('usb', ''),
                                'serial': probe.get('serial', ''),
                                'evdev': probe.get('evdev', '')})
        self._raw.setdefault('identity', [])
        if isinstance(self._raw['identity'], dict):
            self._raw['identity'] = [self._raw['identity']]
        self._raw['identity'].append(dict(self.identities[-1]))

    def __repr__(self):
        return f'<Device {self.slug} {self.usb}/{self.serial}>'


# ---- loading ----

def manufacturer_dir(vendor):
    """Where a device from this maker belongs."""
    slug = ''.join(c if c.isalnum() else '-' for c in vendor.lower()).strip('-')
    return os.path.join(CAPTURES, slug or 'unknown')


def load_all():
    out = []
    for p in sorted(glob.glob(os.path.join(CAPTURES, '*', '*.toml'))):
        with open(p, 'rb') as f:
            out.append(Device(tomllib.load(f), p))
    return out


def by_slug(slug):
    return next((d for d in load_all() if d.slug == slug), None)


def by_usb(usb, serial=None):
    usb = (usb or '').lower()
    for d in load_all():
        for i in d.identities:
            if i.get('usb', '').lower() == usb and (
                    serial is None or i.get('serial') == serial):
                return d
    return None


# ---- what is actually plugged in right now ----

def _sysfs_usb_for(jsdev):
    """Walk /sys from the js node up to the USB device, for id and serial."""
    node = os.path.realpath(f'/sys/class/input/{os.path.basename(jsdev)}/device')
    for _ in range(8):
        vid = os.path.join(node, 'idVendor')
        if os.path.exists(vid):
            rd = lambda n: open(os.path.join(node, n)).read().strip()
            try:
                return f'{rd("idVendor")}:{rd("idProduct")}'.lower(), rd('serial')
            except OSError:
                return None, None
        parent = os.path.dirname(node)
        if parent == node:
            break
        node = parent
    return None, None


HID_USAGE = {0x30: 'X', 0x31: 'Y', 0x32: 'Z', 0x33: 'Rx', 0x34: 'Ry',
             0x35: 'Rz', 0x36: 'Slider', 0x37: 'Dial', 0x38: 'Wheel',
             0x39: 'Hat'}


def _walk_up_for(path, name, levels=8):
    node = os.path.realpath(path)
    for _ in range(levels):
        c = os.path.join(node, name)
        if os.path.exists(c):
            return c
        parent = os.path.dirname(node)
        if parent == node:
            return None
        node = parent
    return None


def _hid_usages(js):
    """Axis usages straight from the report descriptor.  Worth more than evdev:
    it tells a Slider from a Dial, which evdev flattens into ABS_THROTTLE and
    ABS_RUDDER."""
    rd = _walk_up_for(f'/sys/class/input/{os.path.basename(js)}/device',
                      'report_descriptor')
    if not rd:
        return []
    try:
        d = open(rd, 'rb').read()
    except OSError:
        return []
    out, i = [], 0
    while i < len(d):
        b = d[i]
        size = d[i] & 0x03
        size = 4 if size == 3 else size
        if (b >> 2) & 0x03 == 2 and (b >> 4) == 0 and size:
            u = int.from_bytes(d[i + 1:i + 1 + size], 'little') & 0xff
            if u in HID_USAGE:
                out.append(HID_USAGE[u])
        i += 1 + size
    return list(dict.fromkeys(out))


def probe(js):
    """Everything about a connected device that does not need a human."""
    import array
    import fcntl
    JSIOCGAXES, JSIOCGBUTTONS = 0x80016a11, 0x80016a12
    JSIOCGAXMAP, JSIOCGNAME = 0x80406a32, 0x80006a13 | (128 << 16)
    usb, serial = _sysfs_usb_for(js)
    info = {'js': js, 'usb': usb, 'serial': serial, 'hid': _hid_usages(js)}
    try:
        fd = os.open(js, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return info
    try:
        n = array.array('B', [0])
        fcntl.ioctl(fd, JSIOCGBUTTONS, n)
        info['buttons'] = n[0]
        fcntl.ioctl(fd, JSIOCGAXES, n)
        info['axes'] = n[0]
        am = array.array('B', [0] * 64)
        fcntl.ioctl(fd, JSIOCGAXMAP, am)
        info['axmap'] = list(am[:info['axes']])
        nm = array.array('B', [0] * 128)
        fcntl.ioctl(fd, JSIOCGNAME, nm)
        info['evdev'] = bytes(nm).split(b'\x00')[0].decode('utf-8', 'replace')
    finally:
        os.close(fd)
    return info


class Match:
    """A connected device and how well it lines up with the map."""

    def __init__(self, probe_info, device, status):
        self.probe = probe_info
        self.device = device
        self.status = status
        self.js = probe_info['js']

    @property
    def ok(self):
        return self.status == EXACT

    def explain(self):
        if self.status == EXACT:
            return 'known device, unchanged'
        if self.status == DRIFT:
            return ('SAME identity but a DIFFERENT shape -- the buttons may have '
                    'been renumbered, so the grouping in the file is suspect')
        if self.status == RECONFIGURED:
            return ('same shape, new identity -- looks like the same hardware '
                    'after a reconfiguration')
        return 'nothing in the map looks like this'

    def __repr__(self):
        p = self.device.product if self.device else '?'
        return f'<Match {self.js} {p} {self.status}>'


def find_connected():
    """One Match per connected joystick, newest information first."""
    out = []
    devices = load_all()
    for js in sorted(glob.glob('/dev/input/js*')):
        info = probe(js)
        dev = next((d for d in devices if d.matches_identity(info)), None)
        if dev is not None:
            fp = dev.matches_fingerprint(info)
            out.append(Match(info, dev, EXACT if fp is not False else DRIFT))
            continue
        dev = next((d for d in devices if d.matches_fingerprint(info)), None)
        if dev is not None:
            out.append(Match(info, dev, RECONFIGURED))
            continue
        out.append(Match(info, None, UNKNOWN))
    return out


if __name__ == '__main__':
    for m in find_connected():
        dev, usb, serial = m.device, m.probe.get('usb'), m.probe.get('serial')
        if dev is None:
            print(f'{m.js}  {usb or "?"}  — not in the map')
            continue
        btns, axes = dev.unknown()
        flag = '' if m.ok else f'   [{m.status}] {m.explain()}'
        print(f'{m.js}  {dev.product}  ({usb}/{serial}){flag}')
        for line in dev.fingerprint_diff(m.probe) if m.status == DRIFT else []:
            print(f'      changed  {line}')
        print(f'    {dev.n_buttons - len(btns)}/{dev.n_buttons} buttons described, '
              f'{dev.n_axes - len(axes)}/{dev.n_axes} axes')
        for g in dev.groups(bindable=True):
            d = f'  [{", ".join(g.dirs or g.stages)}]' if (g.dirs or g.stages) else ''
            p = f' +push {g.push}' if g.push is not None else ''
            x = f' +axes {g.axes}' if g.axes else ''
            print(f'      {g.kind:16s} {str(g.buttons):22s} {g.label}{d}{p}{x}')
