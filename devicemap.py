#!/usr/bin/env python3
"""Read the device map: what each control on a piece of flight hardware is.

    import devicemap
    dev = devicemap.by_usb('3344:43e8')
    dev.groups('hat4')            # every four-way hat, in press order
    dev.axes(kind='lever')        # every lever, in index order
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
import re
import tomllib
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
#: captures/<manufacturer>/<device>.toml -- the manufacturer is the directory,
#: so the `slug` inside does not have to repeat it and a second brand of pedals
#: does not land in the same pile.
CAPTURES = os.path.join(HERE, 'captures')

#: Where the desks live. A capture belongs to this repo -- it is what the
#: hardware IS, and it was expensive to measure -- but a desk is a fact
#: about a room, and somebody with two rooms, or with their own files kept
#: somewhere synced, has nowhere to put the second one. So: overridable,
#: and every screen that reads desks says which directory it read.
PROFILES = (os.environ.get('SIM_DEVICE_PROFILES')
            or os.path.join(HERE, 'profiles'))

#: How well a connected device lines up with its file.
EXACT = 'exact'                 # identity and fingerprint both agree
DRIFT = 'identity-drift'        # same identity, different shape: data suspect
RECONFIGURED = 'reconfigured'   # same shape, new identity: probably the VPC tool
UNKNOWN = 'unknown'             # nothing in the map looks like it

@dataclass
class Axis:
    index: int
    evdev: str = ''
    hid: str = ''
    rest: str = ''          # centred | min | max | mid
    travel: str = ''        # analog | stepped -- a hat wired to an axis steps
    kind: str = ''
    label: str = ''
    #: How fine this axis actually is: the span it reports end to end, and
    #: how much it wanders while untouched. Both wait on a measurement --
    #: an axis with a noisy centre is not a place to put a trim.
    range: int | None = None
    noise: int | None = None
    #: other axis indices that move when this one does, AS THE HARDWARE IS SET
    #: UP NOW. An axis is not free just because nothing is bound to it: War
    #: Thunder's pitch trim went on the VMAX's right throttle lever because the
    #: file said nothing was there, and it trimmed the aircraft on every power
    #: change because the two levers were clamped together.
    moves_with: list = field(default_factory=list)
    #: why they move together, which decides whether it can be undone:
    #:   'switchable' -- a catch on the device, so this is a MODE not a fact
    #:   'fixed'      -- one piece of plastic, two axes
    #:   ''           -- nothing moves with it
    coupling: str = ''
    note: str = ''
    source: str = 'unknown'

    @property
    def independent(self):
        """False when something else travels with it, so binding this axis
        also drives whatever is on its twin. Check `coupling` before working
        around it: 'switchable' means the answer is a catch on the device, not
        a different layout."""
        return not self.moves_with

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


#: Where the hand has to be, nearest to flying first. HOME is the normal
#: grip with every finger where it lives; EXTENDED keeps the grip and
#: stretches a finger; BASE takes the hand off the grip onto the device;
#: OFF takes it off the device altogether.
LEVELS = ('HOME', 'EXTENDED', 'BASE', 'OFF')

#: Where on the rig a hand can be. A position is a part and a level.
PARTS = ('stick', 'stick_base', 'throttle', 'throttle_base', 'panel')

FINGERS = ('thumb', 'index', 'middle', 'ring', 'pinky')

#: Which way a position points, from the pilot's seat. Closed, because a
#: rule that has to accept "forward" from one capture and "up" from another
#: is a rule written about spelling.
DIRECTIONS = ('up', 'down', 'left', 'right', 'fwd', 'aft', 'cw', 'ccw')

#: Levels that leave the hand in the grip. EXTENDED is not a posture of its
#: own -- the hand has not moved, one finger has -- so a thumb at HOME and a
#: pinky reaching are the same hand in the same place, doing two things.
#: BASE and OFF do move the hand, and then nothing else is happening.
GRIPPED = ('HOME', 'EXTENDED')


@dataclass
class Spot:
    """Somewhere a control can be reached from, and with what.

    A control has a list of these, because most can be reached more than one
    way and the cheapest way is what decides how far it is.

    There is nothing here saying who said so. Only the wizard writes these,
    and only from something you pressed: a spot that exists was measured,
    and a control nobody has reached yet has no spots at all.
    """
    part: str = ''
    level: str = 'HOME'
    finger: str = ''
    #: Filled in from the device this spot belongs to, never written in the
    #: profile: which hand is on a device is said once, per device.
    hand: str = ''

    @property
    def tier(self):
        """How far from flying this spot is. 0 is the normal grip."""
        return LEVELS.index(self.level) if self.level in LEVELS else len(LEVELS)


#: What a position is for, beyond being somewhere to put the control. Empty
#: means it is exactly that -- a hat direction, a trigger detent, a switch
#: end. The rest are contacts the control carries without being places you
#: can leave it.
ROLES = ('push', 'rest', 'travel', 'transient')

#: How a contact answers when asked which way its button points. These words
#: reach a screen in the wizard that reads this map, so they are the wording
#: itself rather than a description of it.
ROLE_SAID = {
    'push': 'push',
    'rest': 'rest contact (inverted)',
    'travel': 'travel contact (held while the lever is used)',
    'transient': 'transient (fires both ways)',
}

#: Controls that stay where you put them. The game sees the button HELD, not
#: pressed, so what sits there is on for as long as the handle is over.
LATCHING = ('switch2', 'switch3', 'latch', 'selector')


@dataclass
class State:
    """One position a control can be in, or one contact it carries.

    `button` is None where a position closes nothing. The centre of an
    ON-OFF-(ON) switch is a real place to leave the handle and the game never
    hears about it, so `emits_signal` records a fact about the switch rather
    than a gap in the capture.
    """
    name: str = ''
    button: int | None = None
    direction: str = ''      # canonical, where the position points somewhere
    role: str = ''           # one of ROLES; empty means it is a position
    latching: bool = False   # stays here when you let go
    emits_signal: bool = True


@dataclass(frozen=True)
class Shape:
    """What a control is, as numbers and flags rather than as a word.

    This is what `kind` was standing in for. The wizard downstream decoded
    `hat4`, `switch3` and `trigger` with three tables of strings to get at
    exactly these, and a table of strings is a rule about spelling.
    """
    positions: int      # places you can put it, not counting its contacts
    latching: bool      # it stays where you leave it
    directional: bool   # its positions point somewhere
    clicks: bool        # it presses in as well
    stepped: bool       # a deeper position keeps the shallower one held
    axes: int           # axes that belong to it


@dataclass
class Group:
    kind: str               # hat4 hat8 trigger switch2 switch3 button paddle
    #: Stable within a device, so a profile can name a control without naming
    #: the buttons it happens to sit on today.
    id: str = ''
    #: Everywhere the control goes and every contact it carries, in press
    #: order. A group need not have any -- a lever is an axis plus,
    #: sometimes, a contact.
    states: list = field(default_factory=list)
    label: str = ''
    cumulative: bool = False  # a deeper stage keeps the shallower ones held
    axes: list = field(default_factory=list)  # axes belonging to this control
    rest: str = ''
    note: str = ''
    source: str = 'unknown'
    #: Ergonomic facts. None and '' mean nobody answered, which is why they
    #: are not stored with the default already in them: a file that writes
    #: down its own guesses cannot tell you afterwards which ones they were.
    hold_ok: bool | None = None
    rapid_ok: bool | None = None
    modifier_ok: bool | None = None
    blind_distinct: str = ''
    accident_risk: str = ''
    #: Filled in from the rig, never from the capture: where a control sits
    #: depends on the desk it is bolted to, not on the hardware. Empty until
    #: a profile is laid over the device.
    access: list = field(default_factory=list)

    def __post_init__(self):
        self.states = [s if isinstance(s, State) else State(**s)
                       for s in self.states]
        self.access = [a if isinstance(a, Spot) else Spot(**a)
                       for a in self.access]

    def fact(self, name):
        """One ergonomic fact, or None where nobody has answered.

        There used to be a table here of what a control of each shape is
        taken to be. It answered every question about every control from
        the day the file was written, which is not the same as knowing,
        and a screen showing it had to keep explaining that it was not an
        answer. Nothing now stands in for you.
        """
        got = getattr(self, name)
        return got if got is not None and got != '' else None

    def told(self, name):
        """Whether somebody answered for this fact."""
        got = getattr(self, name)
        return 'measured' if got is not None and got != '' else 'missing'

    @property
    def shape(self):
        """What this control is, without the word for it."""
        places = self.places
        return Shape(positions=len(places),
                     latching=any(p.latching for p in places),
                     directional=any(p.direction for p in places),
                     clicks=self.push is not None,
                     stepped=bool(self.cumulative),
                     axes=len(self.axes))

    @property
    def tier(self):
        """How far from flying this control is, or None if nobody said.

        The nearest way of reaching it wins: something you can get with a
        thumb without moving is close even when you could also get it from
        the base.
        """
        return min((a.tier for a in self.access), default=None)

    @property
    def places(self):
        """The states that are somewhere to put it, in press order."""
        return [s for s in self.states if not s.role]

    def contact(self, role):
        """The button of the one contact with this role, or None."""
        return next((s.button for s in self.states if s.role == role), None)

    @property
    def buttons(self):
        """Position buttons, in press order."""
        return [s.button for s in self.places if s.button is not None]

    @property
    def push(self):
        """The click a hat, dial or mini-stick also has."""
        return self.contact('push')

    @property
    def names(self):
        """What each position is called, or nothing where none are named.

        A plain button has one position and no word for it. Handing back a
        list of empty strings makes it look like a control with named
        positions to anything that only asks whether the list is empty.
        """
        said = [s.name for s in self.places]
        return said if any(said) else []

    #: One list under three names. A reader asks for whichever it thinks the
    #: control has and gets the same answer -- the split into dirs, stages
    #: and positions was never a fact about the hardware, only about which
    #: shape the person capturing it had in mind.
    dirs = names
    stages = names
    positions = names

    @property
    def transient(self):
        """Contacts that fire on the way past, so again on the way back."""
        return [s.button for s in self.states
                if s.role == 'transient' and s.button is not None]

    @property
    def all_buttons(self):
        """Every button this control owns, bindable or not."""
        return [s.button for s in self.states if s.button is not None]

    @property
    def bindable_buttons(self):
        """What may safely carry an action.

        A rest contact is closed whenever the control is untouched, so anything
        bound to it runs all the time except while you are using the control.
        A transient contact closes partway through the travel and so fires
        again on the way back out -- a weapon bound there goes off twice per
        squeeze. A travel contact trips near the START of a lever's travel and
        stays closed until it is nearly released, so whatever sits on it is
        held down for as long as you are using the lever: countermeasures
        bound there empty the aircraft while you brake. All three are left out
        here and listed in `all_buttons`, so coverage still adds up and a
        consumer that wants one must ask for it.
        """
        if not self.bindable:
            return []
        return [s.button for s in self.states
                if s.button is not None and s.role in ('', 'push')]

    @property
    def bindable(self):
        """A button held down at rest fires continuously; never bind it. Nor
        one the firmware reports with nothing physically behind it."""
        return self.kind not in ('unknown', 'switch-position', 'unwired')

    def direction(self, button):
        """Which way this button points, for a hat or a staged trigger."""
        for s in self.states:
            if s.button is not None and s.button == button:
                return ROLE_SAID[s.role] if s.role else s.name
        return ''


def slug(text):
    """`Top thumb hat` -> `top-thumb-hat`."""
    return re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')


def name_ids(groups):
    """Fill in the `id` of every described group that has none, in place.

    Built from the label, because that is what somebody reading a profile
    recognises: `[device.access."top-thumb-hat"]` says where it is, and a
    counter would not. Where two controls share a label the lowest button
    tells them apart rather than a running number, so capturing a third does
    not renumber the first two.

    The uncaptured bucket is left alone. It is scratch -- it appears and
    empties as the capture goes on -- and a profile has nothing to say about
    buttons nobody has described yet.
    """
    taken = {g['id'] for g in groups if g.get('id')}
    for g in groups:
        if g.get('id') or g.get('kind') == 'unknown':
            continue
        base = slug(g.get('label', '')) or g.get('kind', 'control')
        owned = [st['button'] for st in g.get('states') or []
                 if st.get('button') is not None]
        name = base
        if name in taken and owned:
            name = f'{base}-{min(owned)}'
        n = 2
        while name in taken:
            name, n = f'{base}-{n}', n + 1
        g['id'] = name
        taken.add(name)
    return groups


class Device:
    def __init__(self, data, path):
        self.path = path
        self._raw = data
        d = data['device']
        self.slug = d['slug']
        self.product = d['product']
        self.vendor = d.get('vendor', '')
        self.kind = d.get('kind', '')
        self.n_buttons = d.get('buttons', 0)
        self.n_axes = d.get('axes', 0)
        self.identities = [dict(i) for i in data.get('identity', [])]
        first = self.identities[0] if self.identities else {}
        self.usb = first.get('usb', '').lower()
        self.serial = first.get('serial', '')
        self.evdev_name = first.get('evdev', '')
        self.game_ids = first.get('games', {})
        self.fingerprint = data.get('fingerprint', {})
        self._axes = [Axis(**a) for a in data.get('axis', [])]
        self._groups = [Group(**g) for g in data.get('group', [])]
        # What a rig would say about it, until one does. A device on no
        # desk is under no hand, and the alternative is that every reader
        # has to know whether `under` has been called yet.
        self.profile = None
        self.hand = ''
        self.role = self.kind
        self.releases_flight = False

    def under(self, prof):
        """Lay a rig over this device: which hand, and what reaches what.

        Returns self, because every caller wants the device back and a
        device without a rig is only half an answer.
        """
        said = prof.entry(self.slug) if prof is not None else None
        self.profile = prof
        self.hand = (said or {}).get('hand', '')
        self.role = (said or {}).get('role') or self.kind
        self.releases_flight = bool(
            (said or {}).get('leaving_home_releases_flight'))
        for g in self._groups:
            g.access = (prof.access(self.slug, g.id)
                        if prof is not None and said is not None and g.id
                        else [])
            for spot in g.access:
                spot.hand = self.hand
        return self

    # ---- queries ----

    def axes(self, kind=None, source=None):
        out = self._axes
        if kind:
            out = [a for a in out if a.kind == kind]
        if source:
            out = [a for a in out if a.source == source]
        return out

    def axis(self, index):
        return next((a for a in self._axes if a.index == index), None)

    def axis_group(self, index):
        """The control an axis belongs to, when it is part of one -- a
        mini-stick is two axes and a click, not three unrelated things."""
        return next((g for g in self._groups if index in g.axes), None)

    def groups(self, kind=None, bindable=None):
        out = self._groups
        if kind:
            out = [g for g in out if g.kind == kind]
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


class Profile:
    """One rig: which captured devices are on the desk, and how they sit.

    A capture says what a control IS. A profile says where it ended up. The
    same throttle on a desk and on a chair rail has a different reach and can
    be under a different hand, so none of that belongs in the capture -- and
    `hand` sat in the device file doing nothing for exactly that reason.

    It is also what gives "different hands" a scope. Whether two controls can
    be worked at once is a question about a pair of devices, and a pile of
    capture files is not a pair of anything.
    """

    def __init__(self, data, path):
        self.path = path
        self.name = (data.get('name')
                     or os.path.basename(path).removesuffix('.toml'))
        self.devices = [dict(d) for d in data.get('device', [])]

    def entry(self, slug):
        """What this rig says about one captured device, or None."""
        return next((d for d in self.devices if d.get('slug') == slug), None)

    def access(self, slug, control):
        """Every way of reaching one control, as this rig has it."""
        got = (self.entry(slug) or {}).get('access') or {}
        return [Spot(**a) for a in got.get(control, [])]

    def _as_dict(self):
        """This rig as the tables it was parsed from."""
        return {'name': self.name, 'device': [dict(d) for d in self.devices]}

    def __repr__(self):
        return f'<Profile {self.name}: {len(self.devices)} devices>'


def compatible(a, b):
    """Can these two controls be worked at the same time?

    Different hands and there is nothing to argue about. One hand and it
    comes down to whether there is anywhere that hand can be that reaches
    both, with a different finger for each -- a thumb cannot be on two
    things at once, however close together they are.

    Derived rather than recorded, which is why a profile had to exist: this
    is a question about a pair of devices, and a directory of capture files
    is not a pair of anything. A 39-by-39 table would also have to be filled
    in by hand, and would go stale the moment the rig moved.
    """
    for x in a.access:
        for y in b.access:
            if x.hand and y.hand and x.hand != y.hand:
                return True
            if _one_hand_at_both(x, y):
                return True
    return False


def _one_hand_at_both(x, y):
    """Can a single hand be at both of these spots at once?"""
    if x.part != y.part:
        return False                    # a hand is on one thing at a time
    if not (x.finger and y.finger and x.finger != y.finger):
        return False                    # nor is a finger in two places
    if x.level in GRIPPED and y.level in GRIPPED:
        return True
    return x.level == y.level


def load_profiles():
    """Every rig on file, by name."""
    out = []
    for path in sorted(glob.glob(os.path.join(PROFILES, '*.toml'))):
        with open(path, 'rb') as fh:
            out.append(Profile(tomllib.load(fh), path))
    return out


def profile(name=None, strict=True):
    """The rig to read devices under, or None when there are none on file.

    One profile and it is the one. More than one and the name has to come
    from somewhere -- the argument, `SIM_DEVICE_PROFILE`, or whoever is
    asking. Nothing here guesses which desk you are sitting at: guessing is
    how the wizard that reads this map ended up with two override channels
    and a silent fallback to whichever device loaded last.

    `strict=False` hands back None instead of stopping, for a caller that
    has a way to ask -- the wizard puts the question on a screen. A library
    caller has nobody to ask, so for it the ambiguity is fatal.
    """
    have = load_profiles()
    want = name or os.environ.get('SIM_DEVICE_PROFILE')
    if want:
        hit = next((p for p in have if p.name == want), None)
        if hit is None:
            raise SystemExit(f'no profile called {want!r}'
                             + ('; have ' + ', '.join(p.name for p in have)
                                if have else '; none on file'))
        return hit
    if len(have) == 1:
        return have[0]
    if not have or not strict:
        return None
    raise SystemExit('more than one profile, so which desk this is for cannot '
                     'be decided here.\n  choose with SIM_DEVICE_PROFILE='
                     + '|'.join(p.name for p in have))


def load_all(bare=False, rig=None):
    """Every captured device, under the active rig.

    `bare=True` reads the captures with no rig over them, which is what the
    capture tool wants: it is describing the hardware, not the desk.

    `rig` is that desk, said outright. Without it this asks `profile()`,
    which stops rather than guess when there is more than one -- and a
    caller that has already asked somebody should not be made to set an
    environment variable to say so.
    """
    prof = None if bare else (rig if rig is not None else profile())
    return [d.under(prof) for d in _load_captures()]


def _load_captures():
    out = []
    for p in sorted(glob.glob(os.path.join(CAPTURES, '*', '*.toml'))):
        with open(p, 'rb') as f:
            out.append(Device(tomllib.load(f), p))
    return out



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


def find_connected(rig=None, bare=False):
    """One Match per connected joystick, newest information first.

    `bare=True` answers what is plugged in without a desk over it, which
    is a question the desk does not come into: whether a joystick has a
    capture on file is true at every desk or at none.
    """
    out = []
    devices = load_all(bare=bare, rig=rig)
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
            t = f'  tier {g.tier}' if g.tier is not None else ''
            print(f'      {g.kind:16s} {str(g.buttons):22s} {g.label}{d}{p}{x}{t}')
