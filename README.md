# WARNING WARNING 100% VIBECODED WARNING WARNING

# sim-device-map

What each button and axis on a piece of sim hardware **physically is** — kept
once, in one place, independent of any game.

Covers anything you plug in and then have to bind: a stick, a throttle, rudder
pedals, a button box, a panel. The games disagree about what to call these
devices and none of them knows what the controls *are*; this does.
s

## Scope

A bind wizard needs three things. Two of them are per-game and already solved;
the third is the same for every game and lived nowhere until this repo:

| layer | scope | how it's obtained |
|---|---|---|
| what actions a game has | per game | DCS: `default.lua` through a Lua interpreter · War Thunder: unpack `vromfs` · Elite: bindings XML |
| which actions matter | per game | count how many of the factory joystick profiles the game ships bind each one |
| **what the hardware physically is** | **every game** | **this repo** |

The third layer is what decides *where* a binding goes, and it cannot be
derived from the games. It also cannot be fully derived from the OS:

- **Axes are ~90% discoverable.** The HID report descriptor names the control
  (`X`, `Y`, `Z`, `Rx`, `Ry`, `Slider`, `Dial`) and one resting-position read
  separates a self-centring mini-stick from a lever parked at its minimum.
- **Buttons are 0% discoverable.** VIRPIL firmware flattens hats into plain
  buttons before anything sees them — both devices here report **zero**
  `Hat switch` usages. Nothing in the kernel or in any game knows that
  `js 8,9,10,11` is one hat, that `js 12` and `js 3` are two detents of one
  trigger, or that you can reach `js 26` without letting go of the grip.

So the button layer is captured once by hand (`capture.py`) and then
reused forever. One free exception: a button **held down at rest** is a switch
position rather than a momentary button, and that is detectable — see
`rest = "closed"` below.

## What a device file gives a wizard

Facts, and only facts. What a control is good *for* is a judgement about a
game's actions, and it is made by whatever is choosing bindings -- never
here. The map used to carry it, in a `suits` field, and 39 controls produced
24 different answers: an opinion filed in the facts, matched by string.

What is on offer instead is what the control physically does:

| fact | what it settles |
|---|---|
| `states` | every position it has, whether each one latches, and whether it sends anything |
| `direction` | which way a position points, from the pilot's seat |
| `cumulative` | a deeper trigger detent keeps the shallower one held |
| `axes`, `rest`, `stepped` | whether an axis centres, parks at zero, sweeps or steps |
| `range`, `noise` | how fine it is end to end, and how far it wanders untouched |
| `moves_with`, `coupling` | that two axes travel together as the rig is set up now |
| `access` (in the profile) | where your hand has to be, and which finger |
| `hold_ok`, `rapid_ok`, `modifier_ok` | comfortable held down, clicked fast, used as a shift |
| `blind_distinct`, `accident_risk` | can you find it without looking, can it be pressed by mistake |

The last two rows are ergonomics, and they are the one place a file may say
nothing: `Group.fact` is None until somebody answers, and `Group.told` says
which. **A guess is never written down**: a file that records its own guesses
cannot say afterwards which ones they were.

`blind_distinct` and `accident_risk` are scales, so the file holds `0`, `1`
or `2` — no, somewhat, yes. The word lives in `questions.toml` and can be
reworded; the number is what orders them.
| button held at rest | **nothing** — it would fire continuously |

## Schema

One TOML file per device, read with the stdlib `tomllib`, filed by who made
it:

```
captures/
  virpil/
    vpc-stick-warbrd-d.toml
    vmax-prime-throttle.toml
  <next manufacturer>/
```

The directory carries the manufacturer, so the `slug` inside the file is the
only name code uses and nothing has to be renamed when a second brand arrives.

```toml
[device]                # slug, product, vendor, kind, buttons, axes
                        # kind: one of devicemap.ROLES_ON_A_DESK
[[identity]]            # usb, serial, evdev name, first_seen (a date),
                        # per-game ids
[fingerprint]           # axmap + hid: two independent readings,
                        # NOT paired. Counts are in [device].
[[axis]]                # index, evdev, hid, rest, role,
                        # stepped, range, noise
[[group]]               # kind, id, states, cumulative, axes, label
                        # -- or `status` where the row is not a control
```

An axis does not say what it is or what it is called — the control that owns
it does, and `Axis.kind`/`.label` are filled in from there when the file
loads. Said in both places they drifted: this file had an axis calling itself
a `slider` inside a control called `Left side dial`, and `axes(kind='dial')`
answered *one* where the controls said *two*. `role` is `x` or `y` where a
control has more than one axis, which is all an axis knows about itself that
its control does not.

Every closed field is checked when the file is read, and a word outside its
list raises rather than loading: `kind` against `devicemap.KINDS`, `status`
against `STATUS`, `[device].kind` against `ROLES_ON_A_DESK`, an axis's `rest`
and `coupling` against theirs, and a state's `direction` and `role` against
theirs. A control has a `kind` or a `status`, never both, and an axis has
`moves_with` and `coupling` together or neither. A desk is checked when it is
laid over the captures: its `role`, `hand`, every `level` and `finger`, and
that every control and device it names exists.

The closed lists live in `devicemap` — the reader — and `questions.toml`
holds only the words for them. It refuses to load a descriptor offering a
shape the reader will not accept, so a capture you cannot save is caught
before it is offered.

A control's positions and the contacts it carries are one list. A hat that
clicks has five states -- four directions and the click, marked
`role = "push"` -- so a name can never drift out of step with the button it
belongs to, which is what two parallel lists let it do.

`id` is the control's name inside its device (`top-thumb-hat`), and it is
what a profile points at. Buttons get renumbered by a firmware reflash; the
name does not.

A control is not always only buttons or only axes. A mini-stick is two axes
and usually a click, and recording those as three unrelated things loses the
fact that they are one thing under one thumb:

```toml
kind    = "ministick"
buttons = []
push    = 22          # it presses in
axes    = [3, 4]      # and these are its axes
```

`axes` links a group to `[[axis]]` entries by index; the measured axis facts
stay where they are. `Device.axis_group(3)` goes the other way. An encoder
takes a `push` too, for the same reason.

A trigger records more, because presses alone cannot describe one:

```toml
kind         = "trigger"
buttons      = [2, 3, 4]
stages       = ["first", "second", "third"]
cumulative   = true       # a deeper stage keeps the shallower ones held
rest_contact = 1          # CLOSED while the trigger is untouched
```

`cumulative` is what a game wants to know: pulling through to the third stage
fires everything bound up to it, so guns on the first and cannon on the second
is one squeeze, not a choice between them.

`rest_contact` and `transient` are traps. A rest contact is closed whenever the
trigger is *not* being used, so an action bound to it runs all the time except
while you are firing. A transient contact closes over a band of the travel and
so fires again on the way back out -- a weapon there goes off twice per squeeze.
`Group.bindable_buttons` leaves both out; `all_buttons` includes them, so
coverage still adds up.

`capture.py` works the stages out by watching one pull and release rather than
asking, because they give themselves away by shape: nested intervals are
stages, two pulses in one cycle is a transient, and a button whose first event
is an *up* was closed before you touched anything.

### What the timing cannot tell you

That last one is ambiguous and the tool stops and asks. A trigger's own rest
contact and a **latching lever** sitting in front of it look identical in one
trace -- closed at the start, open through the pull, closed again at the end.
The difference is physical: a rest contact returns on its own, a latch stays
where you put it until you push it back. So `capture.py` asks, and on "no, I
push it back" the button leaves the trigger and is captured as `kind = "latch"`
on its own.

A latch is worth having, and the file says so without an opinion: its states
are marked `latching = true`, so the game sees the button **held** rather
than pressed. What that is good for -- master arm, a modifier, a cover that
gates something -- follows from the fact, and is worked out by whatever is
choosing bindings.

## What the wizard asks

The order and the branching live in `questions.toml`, not in the code that
draws the screens. What they replace is a 215-line function of nested
`if kind ==`, with a second, parallel copy of the same menus for editing --
so editing is now the same walk with answers already in it.

```toml
[[ask]]
id   = "click"
of   = "control"
how  = "press"
only = "can_click"
says = "Does it also click? Press the click in."
sets = "push"
```

`only` names a rule in `questions.py`, never an expression written as text:
a name that does not exist is an error at load, where a bad expression would
be a question that silently never fires.

`of` is what a question is asked ABOUT, and it decides the shape of the
screen rather than just its words:

| `of` | shape | why |
|---|---|---|
| `control` | one at a time, each answer a box you can step back into | you learn what a thing is by pressing it |
| `device` | a round over the whole device | reach is not a fact about one control |
| `all` | one list down every control | these are comparative judgements, and side by side they calibrate each other |

Going back keeps what still applies. Saying a control is a hat8 rather than a
hat4 does not cost you its name; only the answers whose question no longer
applies are dropped, and the screen is told how many went.

## The profile: where it all ended up

A capture says what a control **is**. Where it sits is a fact about the desk,
not the hardware: the same throttle on a chair rail has a different reach and
can be under a different hand. That lives in `profiles/<name>.toml`.

```toml
name = "Biurko"

[[device]]
slug = "virpil-vpc-stick-warbrd-d"
role = "stick"
hand = "right"
leaving_home_releases_flight = true   # in-flight actions stay at HOME

[device.access]
top-thumb-hat = [{ level = "HOME", finger = "thumb" }]
```

`access` is a **list**, because most controls can be reached more than one
way, and the nearest way is the one that decides how far a control is.

| level | where the hand is |
|---|---|
| `HOME` | the normal grip, every finger where it lives |
| `EXTENDED` | still gripping, a finger stretches |
| `BASE` | off the grip, onto the device |
| `OFF` | off the device altogether |

Two things fall out of `access` and are never written down.

**`Group.tier`** is the lowest level any spot needs: the nearest way of
reaching a control, because the awkward way it can *also* be reached says
nothing about how fast it is.

**`devicemap.compatible(a, b)`** is whether two controls can be worked at
once. Different hands and there is nothing to argue about; one hand and it
comes down to whether that hand can be somewhere that reaches both, with a
different finger for each. `EXTENDED` is not a posture of its own -- the hand
has not moved, one finger has -- so a thumb on one control and a pinky
reaching for another is one hand doing two things. `BASE` and `OFF` do move
the hand, and then nothing else is happening.

That second question is why a profile exists at all: it is about a *pair* of
devices, and a directory of capture files is not a pair of anything. The
alternative is a 39-by-39 table filled in by hand, going stale the moment the
rig moves.

With more than one profile on file, say which with `SIM_DEVICE_PROFILE`.
Nothing guesses which desk you are sitting at.

`access` is measured rather than described. `r` in the wizard walks one
round per posture and finger -- *with the thumb, from the normal grip, press
everything you can reach* -- and whatever is never pressed comes out as
`OFF`. Asking control by control would be asking the same question
thirty-nine times, and the answers would not agree with each other.

The ergonomic facts go the other way: `f` puts one question down **every**
control at once, because "more distinct than that one" is a comparison and
comparisons made on separate screens do not line up.

### Which way is "up"

Directions are **physical, from the pilot's seat**, never the effect they
happen to produce in some game:

- **up** = pushed *away* from you, toward the nose
- **down** = pulled *toward* you
- **left / right** = as you see them sitting behind the stick

A hat is hardware; "climb" is a game's interpretation of it. Recording the
effect instead of the direction is how a map ends up inverted against itself,
and the two hats seeded from the DCS captures did exactly that: DCS named
js 10 `Trimmer Switch - PULL(CLIMB)`, which is the hat pulled *toward* the
pilot, and it was seeded as `up` because pulling makes the aircraft climb.
Under the rule above that button is `down`. Both seeded hats are `inferred`
and are corrected by capturing them.

There is no honesty field. A capture reaches the file only once somebody has
described it, so presence *is* the claim: `source = "measured"` sat on every
entry saying nothing, and on things nobody had measured. What is still missing
is missing — `Group.told` answers that per fact, and an unmeasured `stepped`
or `noise` is absent rather than defaulted.

Rows that are not controls carry a `status` instead of a `kind`:

- `uncaptured` — the pile of buttons nobody has pressed yet. `capture.py`
  works through these.
- `unwired` — the firmware reports them and nothing is physically behind them.

## Matching a device

Two layers, because VIRPIL's own configuration tool can change a device's USB
id, its serial and its name in one go:

1. **`[[identity]]`** — USB id + serial. A device may carry *several*: a heavy
   reconfiguration mints a new one, and the old one is worth keeping so a
   machine that has not been reconfigured still recognises it.
2. **`[fingerprint]`** — button count, axis count, axis map, HID usages. This
   survives an identity change, so the same physical hardware is still
   recognisable afterwards.

Never match on the evdev name: VIRPIL bakes the firmware build date into it
(`VIRPIL Controls 20260723 L-VPC ...`), so it changes on every firmware update
— which is also why the DCS GUIDs in `identity.games` have been renumbered
before.

### When the two layers disagree

| identity | fingerprint | status | what it means |
|---|---|---|---|
| ✓ | ✓ | `exact` | nothing to do |
| ✗ | ✓ | `reconfigured` | same hardware, new id. `capture.py` offers to keep both ids |
| ✓ | ✗ | `identity-drift` | **the buttons may have been renumbered** |
| ✗ | ✗ | `unknown` | not in the map |

`identity-drift` is the dangerous one and the reason the fingerprint exists.
If the device now reports a different number of buttons, the numbers in the
file no longer point at the same physical controls, and a wizard reading them
would bind the wrong things with total confidence. `capture.py` says what
changed and offers to throw the grouping away and start over. Silently
re-linking would be worse than not matching at all.

## Who reads it

The bind wizards, which expect this repo as a **sibling directory** -- or
`SIM_DEVICE_MAP` pointing at it:

```
~/Git/
  sim-device-map/          <- devicemap.py + captures/
  dcs-bind-wizard/         ./dcs-bind-wizard.py, then P in the bind table
  warthunder-bind-wizard/  ./plan.py
```

They read exactly two things: `devicemap.py` and `captures/*/*.toml`. Devices
are matched by USB id and serial, so which of `js0`/`js1` a device landed on,
and the order you plugged them in, do not matter.

Change the hardware, and the flow is: capture here, then re-run the wizard in
each game. Nothing in either game's repo describes your devices any more.

## Usage

```bash
./capture.py              # work through the unknown controls
./capture.py --list       # what's known about each connected device

python3 -c 'import devicemap; print(devicemap.find_connected())'
```

It opens on the desk list: which rig this is, because the same throttle on a
chair rail is under a different hand and within reach of different things.
`n` starts one, `e` says which hand is on what. With one desk on file it is
already chosen and you go straight to the devices.

The list asks what a control is. `w` on it asks what a control *does*: every
event labelled from the map as it happens, and what fired together — a button
closing while an axis travels, or two axes reporting the same value. Touch one
control at a time. What it finds about two axes it offers to write down.

```python
import devicemap
dev = devicemap.by_usb('3344:43e8')
dev.groups('hat4')              # every 4-way hat, in press order
dev.axes(kind='lever')          # every lever, in index order
dev.unknown()                   # what still needs capturing

g = dev.axis_group(5)           # the control an axis belongs to
g.bindable_buttons              # excludes rest, travel and transient contacts
g.tier                          # how far from flying, once a profile is on
g.shape                         # positions, latching, directional, clicks...
g.fact('hold_ok')               # the file's answer, or None
g.told('hold_ok')               # 'measured' or 'missing'
devicemap.compatible(g, other)  # can both be worked at once
dev.axis(2).independent         # False when another axis moves with it
```

## Extending a device file

Device files are expensive to rebuild and cheap to extend. Anything learned
about a control — from a capture, from a game's own config, from the owner —
belongs in the file with the right `source`, not in a note elsewhere.

Two questions the file answers only if someone measures them, both under
`w` on the control list:

- whether a button and an axis are **one control** (`travel_contact`,
  `rest_contact`, `transient`)
- whether two axes **move together** (`moves_with`, `coupling`)

Neither is derivable from the OS, and *nothing is bound to it* is not the same
question as *nothing else moves with it*.
