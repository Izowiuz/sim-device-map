"""Turning what the hardware did into what it is.

Four readings, none of which the kernel offers: which axis somebody moved and
whether it sweeps or steps, the order of a rotary selector's positions, the
stages of a trigger, and which captured device the thing now plugged in
actually is.

They are pure functions over event lists and dicts, so none of this needs a
joystick -- which is the point, because the gestures that break them are the
awkward ones nobody performs on purpose.
"""

import glob
import os
import tomllib
import unittest
from unittest import mock

import capture
import devicemap
import fake


class WhetherAnAxisSweeps(unittest.TestCase):
    """A mini-hat wired to axes reports three positions and calls itself an
    axis. Binding an aim or a view to one gives you three, not a sweep."""

    def test_too_little_to_say(self):
        # None and not False. An axis nobody swept far enough is not an
        # axis that sweeps, and the two used to read the same -- which is
        # how an unmeasured one ended up carrying a trim.
        self.assertIsNone(capture.classify_travel([0, 32767]))

    def test_a_hat_pretending(self):
        self.assertIs(True,
                      capture.classify_travel([-32767, 0, 32767, 0, -32767]))

    def test_a_real_sweep(self):
        values = list(range(-32767, 32767, 2000))
        self.assertIs(False, capture.classify_travel(values))

    def test_a_few_values_that_pass_through_the_middle(self):
        # Few distinct values, but one of them sits in the band a hat never
        # reports -- so it travelled rather than jumped.
        self.assertIs(False, capture.classify_travel([-32767, 12000, 32767]))


class ARotarySelector(unittest.TestCase):
    """The position you start on is already closed, so it never sends a
    press. It gives itself away by opening, and that is the only evidence of
    where the sweep began."""

    def test_the_order_falls_out_of_one_sweep(self):
        got = capture.analyse_selector(fake.sweep(10, 11, 12))
        self.assertEqual([10, 11, 12], got['order'])

    def test_one_contact_at_a_time_is_what_makes_it_a_selector(self):
        got = capture.analyse_selector(fake.sweep(10, 11, 12))
        self.assertTrue(got['exclusive'])

    def test_two_closed_at_once_is_not_one(self):
        # Three buttons under one thumb, pressed together. Shaped like a
        # selector, wired like a row of buttons.
        events = [fake.press(1.0, 10), fake.press(1.1, 11),
                  fake.release(1.2, 10), fake.release(1.3, 11)]
        self.assertFalse(capture.analyse_selector(events)['exclusive'])

    def test_a_sweep_that_starts_in_the_middle(self):
        got = capture.analyse_selector(fake.sweep(11, 12))
        self.assertEqual(11, got['order'][0])


class AStagedTrigger(unittest.TestCase):
    """One squeeze, two or three detents. The stages nest -- the second
    closes while the first is held and opens before it -- and that nesting is
    what tells a trigger from several buttons under one finger."""

    def test_the_stages_come_out_in_order(self):
        got = capture.analyse_trigger(fake.squeeze(2, 3, 4))
        self.assertEqual([2, 3, 4], got['stages'])

    def test_a_deeper_stage_keeps_the_shallower_one_held(self):
        got = capture.analyse_trigger(fake.squeeze(2, 3, 4))
        self.assertTrue(got['cumulative'])

    def test_one_detent_is_not_cumulative(self):
        got = capture.analyse_trigger(fake.squeeze(2))
        self.assertEqual([2], got['stages'])
        self.assertFalse(got['cumulative'])

    def test_a_contact_closed_at_rest(self):
        # Button 1 is closed before the squeeze starts: it opens as the
        # trigger moves and closes again when it comes back.
        events = ([fake.release(1.0, 1)] + fake.squeeze(2, 3, start=1.1)
                  + [fake.press(2.0, 1)])
        got = capture.analyse_trigger(events)
        self.assertEqual(1, got['rest'])
        self.assertEqual([2, 3], got['stages'])

    def test_a_contact_that_opens_and_never_comes_back(self):
        # A separate latching lever pushed out of the way by hand, not the
        # trigger's own rest contact -- it does not return on its own.
        events = [fake.release(1.0, 1)] + fake.squeeze(2, start=1.1)
        self.assertIsNone(capture.analyse_trigger(events)['rest'])

    def test_a_contact_that_fires_on_the_way_past(self):
        events = fake.squeeze(2, 3, start=1.0)
        events += [fake.press(1.05, 9), fake.release(1.06, 9),
                   fake.press(1.35, 9), fake.release(1.36, 9)]
        got = capture.analyse_trigger(sorted(events))
        self.assertIn(9, got['transient'])
        self.assertNotIn(9, got['stages'])


class WhichDeviceThisIs(unittest.TestCase):
    """Matching is by USB id and fingerprint, never by name: a firmware
    update renames the device and must not lose it."""

    def dev(self, **kw):
        # The counts live in `[device]` and only there. They used to sit in
        # the fingerprint as well, and nothing ever checked the two agreed.
        return fake.device(buttons=12,
                           axes=[fake.axis(n) for n in range(5)],
                           fingerprint={'axmap': [0, 1, 2, 3, 4],
                                        'hid': ['X', 'Y', 'Z', 'Rx', 'Ry']},
                           **kw)

    def test_the_same_stick(self):
        d = self.dev()
        self.assertTrue(d.matches_identity(fake.probed(d)))

    def test_a_different_serial_is_a_different_stick(self):
        d = self.dev()
        self.assertFalse(d.matches_identity(fake.probed(d, serial='OTHER')))

    def test_usb_ids_match_whatever_their_case(self):
        d = self.dev(usb='3344:81E6')
        self.assertTrue(d.matches_identity(fake.probed(d, usb='3344:81e6')))

    def test_a_renamed_device_is_still_the_same_one(self):
        d = self.dev()
        probe = fake.probed(d, evdev='VIRPIL Controls 20261231 Stick')
        self.assertTrue(d.matches_identity(probe))

    def test_no_fingerprint_recorded_cannot_say(self):
        d = fake.device()
        self.assertIsNone(d.matches_fingerprint(fake.probed(d)))

    def test_a_moved_button_shows_up_in_the_fingerprint(self):
        d = self.dev()
        self.assertFalse(d.matches_fingerprint(fake.probed(d, buttons=13)))

    def test_the_diff_says_what_moved(self):
        d = self.dev()
        said = d.fingerprint_diff(fake.probed(d, buttons=13))
        self.assertEqual(['buttons: 12 -> 13'], said)


class WhatIsPluggedIn(unittest.TestCase):
    """`find_connected` is the glue, and the four verdicts it can reach are
    what every screen downstream branches on."""

    def connected(self, devices, probes):
        with mock.patch.object(devicemap, 'load_all',
                               lambda bare=False, rig=None: devices), \
             mock.patch.object(devicemap.glob, 'glob',
                               lambda _p: sorted(probes)), \
             mock.patch.object(devicemap, 'probe', lambda js: probes[js]):
            return devicemap.find_connected()

    def fingerprinted(self, **kw):
        return fake.device(buttons=12,
                           axes=[fake.axis(n) for n in range(5)],
                           fingerprint={'axmap': [0, 1, 2, 3, 4],
                                        'hid': ['X', 'Y']}, **kw)

    def test_the_stick_it_was_captured_on(self):
        d = self.fingerprinted()
        got, = self.connected([d], {'/dev/input/js0': fake.probed(d)})
        self.assertEqual(devicemap.EXACT, got.status)
        self.assertTrue(got.ok)

    def test_the_same_stick_with_its_buttons_moved(self):
        # Right identity, wrong shape: the firmware was reflashed and the
        # grouping captured by hand may no longer describe it.
        d = self.fingerprinted()
        got, = self.connected([d], {'/dev/input/js0':
                                    fake.probed(d, buttons=13)})
        self.assertEqual(devicemap.DRIFT, got.status)
        self.assertFalse(got.ok)

    def test_the_same_shape_under_a_new_identity(self):
        d = self.fingerprinted()
        probe = fake.probed(d, usb='1234:5678', serial='NEW')
        got, = self.connected([d], {'/dev/input/js0': probe})
        self.assertEqual(devicemap.RECONFIGURED, got.status)
        self.assertIs(d, got.device)

    def test_something_nobody_captured(self):
        d = self.fingerprinted()
        probe = fake.probed(usb='9999:9999', serial='X', buttons=4, axes=2)
        got, = self.connected([d], {'/dev/input/js0': probe})
        self.assertEqual(devicemap.UNKNOWN, got.status)
        self.assertIsNone(got.device)

    def test_every_verdict_explains_itself(self):
        d = self.fingerprinted()
        for probe in (fake.probed(d),
                      fake.probed(d, buttons=13),
                      fake.probed(d, usb='1234:5678', serial='NEW'),
                      fake.probed(usb='9:9', serial='X', buttons=4, axes=2)):
            got, = self.connected([d], {'/dev/input/js0': probe})
            with self.subTest(status=got.status):
                self.assertTrue(got.explain())


if __name__ == '__main__':
    unittest.main()


class AnAxisIsAControlToo(unittest.TestCase):
    """It has a reach, an ergonomics, and it is something you bind — all
    of which live on a group. Two of the throttle's three levers sat with
    none of it: described, measured, and unable to say which finger gets
    them, while the brake lever beside them said `tier 0` for no better
    reason than that it also has a button to press."""

    def dev(self, *axes, groups=()):
        return fake.device(kind='stick', groups=list(groups),
                           axes=[dict(a) for a in axes])

    def test_an_axis_nothing_owned_gets_a_control(self):
        got = self.dev({'index': 4})
        one = got.axis_group(4)
        assert one is not None
        self.assertIn('axis 4', one.label)
        self.assertEqual([4], one.axes)

    def test_and_it_can_carry_what_every_control_carries(self):
        got = self.dev({'index': 4})
        one = got.axis_group(4)
        assert one is not None
        self.assertTrue(one.id)
        self.assertTrue(one.bindable)
        self.assertIsNone(one.tier)
        self.assertIsNone(one.fact('blind_distinct'))

    def test_one_a_control_already_owned_is_left_alone(self):
        got = self.dev({'index': 5},
                       groups=[fake.group('dial', [], label='Wheel',
                                          id='wheel', axes=[5])])
        self.assertEqual(1, len([g for g in got.groups() if 5 in g.axes]))

    def test_what_a_thing_is_has_one_answer(self):
        # Asked of the axis table and of the control table, `dial` used
        # to come back different -- an axis calling itself a `slider`
        # inside a control called a dial, and whichever a caller happened
        # to ask decided whether a trim could go there.
        got = self.dev({'index': 5},
                       groups=[fake.group('dial', [], label='Wheel',
                                          id='wheel', axes=[5])])
        self.assertEqual([5], [a.index for a in got.axes(kind='dial')])
        self.assertEqual([[5]], [g.axes for g in got.groups('dial')])

    def test_and_which_axis_of_its_control_it_is(self):
        got = self.dev({'index': 0, 'role': 'x'}, {'index': 1, 'role': 'y'},
                       groups=[fake.group('ministick', [], label='Mini',
                                          id='mini', axes=[0, 1])])
        self.assertEqual(['x', 'y'], [a.role for a in got.axes()])
        self.assertEqual([0, 1], [a.index for a in got.axes(kind='ministick')])

    def test_an_undescribed_one_still_gets_a_control(self):
        # The pile of buttons nobody has pressed is a `status` now, so an
        # axis cannot land in it however little is known about it. What
        # it gets is a shape of `axis` and a label saying which.
        got = self.dev({'index': 0})
        one = got.axis_group(0)
        assert one is not None
        self.assertEqual('axis', one.kind)
        self.assertFalse(one.status)
        self.assertIn('axis 0', one.label)

    def test_it_says_nothing_the_writer_would_leave_out(self):
        # An empty `states` is the default, and the writer omits it. Put
        # in here, every such control differed from its own file for ever.
        got = self.dev({'index': 4})
        raw = next(g for g in got._raw['group'] if g.get('axes') == [4])
        self.assertNotIn('states', raw)


class AnAxisDoesNotNameItself(unittest.TestCase):
    """The file held two answers to `what is this` -- one on the axis, one
    on the control that owns it -- and they drifted: an axis calling
    itself a `slider` inside a control called `Left side dial`. Which
    answer you got depended on which table you happened to ask."""

    def dev(self):
        return fake.device(
            kind='throttle',
            axes=[fake.axis(0), fake.axis(1), fake.axis(2, rest='min')],
            groups=[fake.group('ministick', [], label='Thumb mini-stick',
                               id='mini', axes=[0, 1]),
                    fake.group('dial', [], label='Left side dial',
                               id='left-side-dial', axes=[2])])

    def test_the_file_may_not_say_it_twice(self):
        for said in ({'index': 0, 'kind': 'dial'},
                     {'index': 0, 'label': 'Slider'}):
            with self.subTest(said=said):
                with self.assertRaises(TypeError):
                    fake.device(axes=[said])

    def test_both_tables_answer_the_same(self):
        got = self.dev()
        self.assertEqual([2], [a.index for a in got.axes(kind='dial')])
        self.assertEqual([[2]], [g.axes for g in got.groups('dial')])

    def test_an_axis_takes_what_its_control_says(self):
        one = self.dev().axis(2)
        assert one is not None
        self.assertEqual('dial', one.kind)
        self.assertEqual('Left side dial', one.label)

    def test_an_axis_on_its_own_names_nothing(self):
        # Not an AttributeError, and not a guess either: an axis with no
        # control behind it has no answer to `what is this`.
        bare = devicemap.Axis(index=0)
        self.assertEqual('', bare.kind)
        self.assertEqual('', bare.label)

    def test_and_says_which_axis_of_it_it_is(self):
        got = fake.device(
            kind='throttle',
            axes=[fake.axis(0, role='x'), fake.axis(1, role='y')],
            groups=[fake.group('ministick', [], label='Mini', id='m',
                               axes=[0, 1])])
        self.assertEqual(['Mini (x)', 'Mini (y)'],
                         [got.axis_label(n) for n in (0, 1)])

    def test_asking_by_kind_finds_every_axis_of_that_control(self):
        # A mini-stick is one control and two axes. Asked of the axis
        # table it used to answer with whichever of them happened to
        # carry the matching word.
        got = self.dev()
        self.assertEqual([0, 1], [a.index for a in got.axes(kind='ministick')])


class TheFingerprintIsTwoReadingsNotOne(unittest.TestCase):
    """`axmap` is the kernel's, in joystick-axis order. `hid` is the
    report descriptor's, in its own. Zipped into pairs they read like a
    fact and are not one: this map briefly claimed kernel code 2 carried
    HID `Ry`, while the axis that code belongs to is `ABS_Z`, usage `Z`."""

    def test_the_two_orders_are_not_the_same_order(self):
        # The real capture, because this is where it showed: the axis
        # table pairs them correctly and the two lists do not agree with
        # that pairing.
        dev = next(d for d in devicemap.load_all(bare=True)
                   if d.kind == 'stick')
        by_axis = [a.hid for a in dev.axes()]
        self.assertNotEqual(by_axis, dev.fingerprint['hid'])

    def test_which_axis_carries_which_usage_is_on_the_axis(self):
        dev = next(d for d in devicemap.load_all(bare=True)
                   if d.kind == 'stick')
        for a in dev.axes():
            with self.subTest(axis=a.index):
                self.assertTrue(a.hid)
                self.assertTrue(a.evdev)

    def test_the_file_keeps_them_as_two_lists(self):
        for path in sorted(glob.glob(os.path.join(devicemap.CAPTURES,
                                                  '*', '*.toml'))):
            with open(path, 'rb') as fh:
                fp = tomllib.load(fh).get('fingerprint') or {}
            with self.subTest(path=os.path.basename(path)):
                self.assertIsInstance(fp.get('axmap'), list)
                self.assertIsInstance(fp.get('hid'), list)
                # Not one list of pairs. A pair asserts an alignment that
                # neither reading gives.
                for v in fp.values():
                    self.assertFalse(any(isinstance(x, dict) for x in v))
