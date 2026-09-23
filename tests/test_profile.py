"""The rig: which devices are on the desk, and what reaches what.

A capture says what a control IS. A profile says where it ended up, and that
is a fact about the desk -- the same throttle on a chair rail has a different
reach and can be under a different hand.

Two things here are worth more than the rest. `tier` has to be the nearest
way of reaching a control, because everything downstream sorts by it; and the
census at the bottom is a snapshot rather than a rule, because the claim the
migration makes is "nothing moved" and only a snapshot can catch a silent
move.
"""

import os
import unittest
from unittest import mock

import devicemap
import fake


def a_rig(access=None, slug='fake-stick', hand='right', role='stick',
          releases=False):
    """A profile with one device in it."""
    d = {'slug': slug, 'role': role, 'hand': hand,
         'access': access or {}}
    if releases:
        d['leaving_home_releases_flight'] = True
    return devicemap.Profile({'name': 'Test', 'device': [d]}, '<fake>')


class HowFarAControlIs(unittest.TestCase):
    def under(self, spots):
        dev = fake.device(groups=[fake.group('button', [0], label='Pinky',
                                             id='pinky')])
        return dev.under(a_rig({'pinky': spots})).groups()[0]

    def test_the_normal_grip_is_nearest(self):
        g = self.under([{'part': 'stick', 'level': 'HOME', 'finger': 'thumb'}])
        self.assertEqual(0, g.tier)

    def test_stretching_a_finger_costs_one(self):
        g = self.under([{'part': 'stick', 'level': 'EXTENDED',
                         'finger': 'pinky'}])
        self.assertEqual(1, g.tier)

    def test_letting_go_of_the_device_costs_most(self):
        g = self.under([{'part': 'panel', 'level': 'OFF'}])
        self.assertEqual(3, g.tier)

    def test_the_nearest_way_wins(self):
        # Reachable from the base as well as under the thumb. It is a thumb
        # control: the awkward way it can also be reached says nothing about
        # how fast it is.
        g = self.under([{'part': 'stick_base', 'level': 'BASE'},
                        {'part': 'stick', 'level': 'HOME',
                         'finger': 'thumb'}])
        self.assertEqual(0, g.tier)

    def test_nobody_said_is_not_the_same_as_far(self):
        # None rather than a middling number. A control nobody measured and
        # a control you have to let go for are different things, and a
        # default would let the first quietly pass for the second.
        self.assertIsNone(self.under([]).tier)


class LayingARigOverADevice(unittest.TestCase):
    def dev(self):
        return fake.device(groups=[fake.group('button', [0], label='Pinky',
                                              id='pinky')])

    def test_the_hand_comes_from_the_rig(self):
        # It used to sit in the capture doing nothing, because a pile of
        # capture files is not a desk and nothing could act on it.
        self.assertEqual('right', self.dev().under(a_rig()).hand)

    def test_a_device_the_rig_does_not_mention(self):
        got = self.dev().under(a_rig(slug='something-else'))
        self.assertEqual('', got.hand)
        self.assertEqual([], got.groups()[0].access)

    def test_no_rig_at_all(self):
        got = self.dev().under(None)
        self.assertEqual('', got.hand)
        self.assertIsNone(got.groups()[0].tier)

    def test_the_role_falls_back_to_what_the_thing_is(self):
        got = self.dev().under(a_rig(role=''))
        self.assertEqual('stick', got.role)

    def test_letting_go_of_this_one_drops_the_aeroplane(self):
        self.assertTrue(self.dev().under(a_rig(releases=True)).releases_flight)
        self.assertFalse(self.dev().under(a_rig()).releases_flight)


class WhichRig(unittest.TestCase):
    """Nothing guesses which desk you are sitting at. Guessing is how the
    wizard that reads this map ended up with two override channels and a
    silent fallback to whichever device loaded last."""

    def with_profiles(self, *names):
        made = [devicemap.Profile({'name': n}, f'<{n}>') for n in names]
        return mock.patch.object(devicemap, 'load_profiles', lambda: made)

    def test_one_rig_needs_no_choosing(self):
        with self.with_profiles('Biurko'):
            got = devicemap.profile()
            assert got is not None
            self.assertEqual('Biurko', got.name)

    def test_none_on_file_is_not_an_error(self):
        with self.with_profiles():
            self.assertIsNone(devicemap.profile())

    def test_two_rigs_refuse_to_be_guessed(self):
        with self.with_profiles('Biurko', 'Fotel'):
            with self.assertRaises(SystemExit) as caught:
                devicemap.profile()
            self.assertIn('Fotel', str(caught.exception))

    def test_the_environment_decides(self):
        with self.with_profiles('Biurko', 'Fotel'):
            with mock.patch.dict(os.environ,
                                 {'SIM_DEVICE_PROFILE': 'Fotel'}):
                got = devicemap.profile()
                assert got is not None
                self.assertEqual('Fotel', got.name)

    def test_asking_for_one_that_is_not_there(self):
        with self.with_profiles('Biurko'):
            with self.assertRaises(SystemExit):
                devicemap.profile('Fotel')


class UnderEachRig:
    """Every capture, laid under every desk on file, one at a time.

    Not `load_all()`: that asks which desk this is, and the answer is on
    the disk of whoever is running these. Each rule below holds at every
    desk, so every desk is what it is checked against.
    """

    def under_each_rig(self):
        for rig in devicemap.load_profiles() or [None]:
            for dev in devicemap.load_all(bare=rig is None, rig=rig):
                yield dev


class TheRigOnFile(UnderEachRig, unittest.TestCase):
    """The profile this repo ships, held to the captures it names."""

    @classmethod
    def setUpClass(cls):
        cls.rigs = devicemap.load_profiles()
        cls.devs = devicemap._load_captures()

    def test_there_is_one(self):
        self.assertTrue(self.rigs)

    def test_every_device_it_names_was_captured(self):
        have = {d.slug for d in self.devs}
        for rig in self.rigs:
            for said in rig.devices:
                with self.subTest(slug=said['slug']):
                    self.assertIn(said['slug'], have)

    def test_every_control_it_names_exists(self):
        for rig in self.rigs:
            for said in rig.devices:
                dev = next(d for d in self.devs if d.slug == said['slug'])
                ids = {g.id for g in dev.groups() if g.id}
                for named in (said.get('access') or {}):
                    with self.subTest(slug=said['slug'], ctrl=named):
                        self.assertIn(named, ids)

    def test_it_speaks_the_vocabulary(self):
        for rig in self.rigs:
            for said in rig.devices:
                self.assertIn(said.get('hand'), ('left', 'right'))
                for ctrl, spots in (said.get('access') or {}).items():
                    for spot in spots:
                        with self.subTest(ctrl=ctrl):
                            self.assertIn(spot['part'], devicemap.PARTS)
                            self.assertIn(spot['level'], devicemap.LEVELS)
                            self.assertIn(spot.get('finger', ''),
                                          ('',) + devicemap.FINGERS)

    def test_a_control_nobody_has_reached_has_no_tier(self):
        # Not tier 0, and not the furthest either. Until somebody walks
        # the fingers there is no answer, and a number here would be one
        # the solver could not tell from a measured one.
        for dev in self.under_each_rig():
            for g in dev.groups(bindable=True):
                if not g.access:
                    with self.subTest(dev=dev.slug, ctrl=g.label):
                        self.assertIsNone(g.tier)

    def test_nothing_unwired_pretends_to_be_reachable(self):
        for dev in self.under_each_rig():
            for g in dev.groups():
                if g.bindable:
                    continue
                with self.subTest(dev=dev.slug, ctrl=g.label):
                    self.assertEqual([], g.access)


class ADeviceOnNoDesk(unittest.TestCase):
    """A capture read on its own is under no hand and reaches nothing."""

    def test_it_says_so_rather_than_having_no_answer_at_all(self):
        dev = fake.device(groups=[fake.group('button', [0], id='one')])
        self.assertEqual('', dev.hand)
        self.assertIsNone(dev.profile)
        self.assertFalse(dev.releases_flight)

    def test_its_role_is_what_it_is_until_a_rig_says_otherwise(self):
        dev = fake.device(kind='throttle')
        self.assertEqual('throttle', dev.role)


class WhatTheRigHasNotBeenTold(UnderEachRig, unittest.TestCase):
    """The profile ships with no `access` at all.

    It used to ship with the old `reach` prose migrated into spots, which
    meant every screen had a third state for "there is data but nobody
    measured it" -- and the numbers in this file pinned that migration as
    if it were a measurement. Both are gone.
    """

    def test_the_rig_says_nothing_about_reach_yet(self):
        for rig in devicemap.load_profiles():
            for said in rig.devices:
                with self.subTest(slug=said['slug']):
                    self.assertFalse(said.get('access'))

    def test_so_no_control_has_a_tier(self):
        for dev in self.under_each_rig():
            for g in dev.groups(bindable=True):
                with self.subTest(dev=dev.slug, ctrl=g.label):
                    self.assertIsNone(g.tier)


if __name__ == '__main__':
    unittest.main()


class WhichDeskThisIs(unittest.TestCase):
    """More than one rig on file and nothing here knows which you are at.

    Guessing is how the wizard downstream ended up with two override
    channels and a silent fallback to whichever device loaded last.
    """

    def rigs(self, *names):
        return [devicemap.Profile({'name': n, 'device': []}, f'<{n}>')
                for n in names]

    def profile(self, names, **kw):
        with mock.patch.object(devicemap, 'load_profiles',
                               lambda: self.rigs(*names)), \
             mock.patch.dict(os.environ, {}, clear=True):
            return devicemap.profile(**kw)

    def test_one_rig_is_the_one(self):
        got = self.profile(['Biurko'])
        assert got is not None
        self.assertEqual('Biurko', got.name)

    def test_none_on_file_is_not_an_error(self):
        self.assertIsNone(self.profile([]))

    def test_two_rigs_stop_a_caller_that_cannot_ask(self):
        with self.assertRaises(SystemExit):
            self.profile(['Biurko', 'Fotel'])

    def test_but_not_one_that_can(self):
        self.assertIsNone(self.profile(['Biurko', 'Fotel'], strict=False))

    def test_naming_it_settles_it_either_way(self):
        for strict in (True, False):
            with self.subTest(strict=strict):
                got = self.profile(['Biurko', 'Fotel'], name='Fotel',
                                   strict=strict)
                assert got is not None
                self.assertEqual('Fotel', got.name)

    def test_a_name_nothing_answers_to_is_an_error_even_when_it_can_ask(self):
        # A rig you named and have not got is a typo, not a question.
        with self.assertRaises(SystemExit):
            self.profile(['Biurko'], name='Fotel', strict=False)


class ReadingDevicesUnderAGivenRig(unittest.TestCase):

    def test_the_rig_you_hand_it_is_the_one_it_uses(self):
        rig = devicemap.Profile({'name': 'x', 'device': [
            {'slug': 'virpil-vmax-prime-throttle', 'hand': 'right'}]}, '<x>')
        got = devicemap.load_all(rig=rig)
        one = next(d for d in got
                   if d.slug == 'virpil-vmax-prime-throttle')
        self.assertEqual('right', one.hand)

    def test_and_it_never_asks_which_desk_this_is(self):
        rig = devicemap.Profile({'name': 'x', 'device': []}, '<x>')
        def boom():
            raise AssertionError('asked anyway')
        with mock.patch.object(devicemap, 'profile', boom):
            self.assertTrue(devicemap.load_all(rig=rig))

    def test_bare_means_no_desk_at_all(self):
        for d in devicemap.load_all(bare=True):
            with self.subTest(dev=d.slug):
                self.assertEqual('', d.hand)


class WithMoreThanOneDeskOnFile(unittest.TestCase):
    """The tool has to start. Which desk this is, it asks on a screen."""

    def two(self):
        return [devicemap.Profile({'name': n, 'device': []}, f'<{n}>')
                for n in ('Biurko', 'Fotel')]

    def test_what_is_plugged_in_is_asked_without_a_desk(self):
        # Whether a joystick has a capture on file is true at every desk
        # or at none, so the question does not come into it.
        def asked(*a, **kw):
            raise AssertionError('asked which desk anyway')

        with mock.patch.object(devicemap, 'profile', asked), \
             mock.patch.object(devicemap.glob, 'glob', lambda _p: []):
            self.assertEqual([], devicemap.find_connected(bare=True))

    def test_the_wizard_starts_rather_than_stopping(self):
        import capture
        opened = []
        with mock.patch.object(devicemap, 'load_profiles', self.two), \
             mock.patch.object(devicemap.glob, 'glob', lambda _p: []), \
             mock.patch.object(capture.curses, 'wrapper',
                               lambda fn, *a: opened.append(a)), \
             mock.patch.object(capture.sys, 'argv', ['capture.py']), \
             mock.patch.dict(os.environ, {}, clear=True):
            capture.main()
        self.assertEqual([(None,)], opened)
