# sim-device-map

What each button and axis on a piece of sim hardware **physically is** — kept
once, in one place, independent of any game.

Covers anything you plug in and then have to bind: a stick, a throttle, rudder
pedals, a button box, a panel. The games disagree about what to call these
devices and none of them knows what the controls *are*; this does.
s

## Why this exists

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

The grouping is the payload, because sensible defaults fall out of it:

| physical shape | what it wants |
|---|---|
| 4-way hat | four related directional actions (views, trim, sensor) |
| 2-position switch | one *toggle* action on **both** ends — every flip changes state |
| 3-position switch | a stepped pair (flaps up/down), centre left empty |
| multi-stage trigger | fire groups in escalating order |
| self-centring mini-stick | a pair of aim/view/cue axes |
| lever resting at minimum | an absolute axis where zero means off (brakes, zoom) |
| dial | trim, prop pitch, zoom |
| paddle | a reflex action (countermeasures) |
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
[device]                # slug, product, vendor, kind, hand, buttons, axes
                        # kind: stick | throttle | pedals | panel | wheel
[[identity]]            # usb, serial, evdev name, first_seen, per-game ids
[fingerprint]           # buttons, axes, axmap, hid usages
[[axis]]                # index, evdev, hid, rest, kind, label, suits, source
[[group]]               # kind, buttons, dirs/stages, push, label, reach, suits, source
```

A hat that also clicks keeps its four directions in `buttons` and the click in
`push`, so the direction names never drift out of step with the button list.

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

A latch is worth having: the game sees the button **held**, not pressed, so it
suits a state that is on while the lever is over -- master arm, a modifier, a
cover that gates something -- which is what the `state` entry in `suits` is
for.

### What `suits` means

The bridge between a physical shape and a game's actions: what kind of thing
this control is good for, so a wizard can choose what to put on it.

Buttons: `reflex` (hit without thinking, no regrip) · `fire` ·
`fire-escalating` · `release` · `lock` · `sensor` · `view` · `trim` ·
`toggle` (flip and leave) · `stepped-pair` · `occasional` (you can afford to
look for it) · `guarded` (must not be hit by accident).

Axes: `flight-roll` · `flight-pitch` · `flight-yaw` · `throttle` ·
`collective` · `brake` · `view` · `cue` · `aim` · `zoom` · `trim` ·
`prop-pitch` · `sweep` · `radiator`.

`reflex` and `occasional` are the two that carry the most weight, and they come
straight from `reach`: a control the pinky reaches without regripping can hold
countermeasures; one that needs letting go of the stick cannot, however
convenient it looks on a diagram.

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

`source` is the honesty field, and every consumer should respect it:

- `measured` — read from HID, evdev or a probe. Trust it.
- `inferred` — reconstructed from how the owner bound this device in another
  game, or from reasoning. Usually right, occasionally not: the throttle's
  js 3/4/6 were seeded as a thumb button plus a three-position switch and turned
  out, on the first capture pass, to be directions of a hat. `capture.py`
  offers to replace whatever a captured control overlaps, so a wrong guess never
  becomes permanent.
- `unknown` — not yet captured. `capture.py` works through these.

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

### The two layers disagreeing is the point

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

```python
import devicemap
dev = devicemap.by_usb('3344:43e8')
dev.groups('hat4')              # every 4-way hat, in press order
dev.axes(suits='view')          # axes that suit head-look
dev.unknown()                   # what still needs capturing
```

## A note for whoever reads this next

These files are the accumulated answer to "what is this knob". They are
expensive to rebuild and cheap to extend. When you learn something concrete
about a control — from a capture, from a game's own config, from the owner
telling you — write it back into the device file with the right `source`,
rather than keeping it in one conversation.
