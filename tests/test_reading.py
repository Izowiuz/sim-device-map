"""Turning what the hardware did into what it is.

Four readings, none of which the kernel offers: which axis somebody moved and
whether it sweeps or steps, the order of a rotary selector's positions, the
stages of a trigger, and which captured device the thing now plugged in
actually is.

They are pure functions over event lists and dicts, so none of this needs a
joystick -- which is the point, because the gestures that break them are the
awkward ones nobody performs on purpose.
"""

import unittest
from unittest import mock

import capture
import devicemap
import fake


class WhetherAnAxisSweeps(unittest.TestCase):
    """A mini-hat wired to axes reports three positions and calls itself an
    axis. Binding an aim or a view to one gives you three, not a sweep."""

    def test_too_little_to_say(self):
        self.assertEqual('', capture.classify_travel([0, 32767]))

    def test_a_hat_pretending(self):
        self.assertEqual('stepped',
                         capture.classify_travel([-32767, 0, 32767, 0, -32767]))

    def test_a_real_sweep(self):
        values = list(range(-32767, 32767, 2000))
        self.assertEqual('analog', capture.classify_travel(values))

    def test_a_few_values_that_pass_through_the_middle(self):
        # Few distinct values, but one of them sits in the band a hat never
        # reports -- so it travelled rather than jumped.
        self.assertEqual('analog',
                         capture.classify_travel([-32767, 12000, 32767]))


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
        return fake.device(fingerprint={'buttons': 12, 'axes': 5,
                                        'axmap': [0, 1, 2, 3, 4],
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
        with mock.patch.object(devicemap, 'load_all', lambda: devices), \
             mock.patch.object(devicemap.glob, 'glob',
                               lambda _p: sorted(probes)), \
             mock.patch.object(devicemap, 'probe', lambda js: probes[js]):
            return devicemap.find_connected()

    def fingerprinted(self, **kw):
        return fake.device(fingerprint={'buttons': 12, 'axes': 5,
                                        'axmap': [0, 1, 2, 3, 4],
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
