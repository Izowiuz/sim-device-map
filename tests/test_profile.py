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


class TheRigOnFile(unittest.TestCase):
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

    def test_everything_you_can_bind_can_be_reached(self):
        for dev in devicemap.load_all():
            for g in dev.groups(bindable=True):
                with self.subTest(dev=dev.slug, ctrl=g.label):
                    self.assertTrue(g.access)

    def test_nothing_unwired_pretends_to_be_reachable(self):
        for dev in devicemap.load_all():
            for g in dev.groups():
                if g.bindable:
                    continue
                with self.subTest(dev=dev.slug, ctrl=g.label):
                    self.assertEqual([], g.access)


class WhereTheRigPutThings(unittest.TestCase):
    """A snapshot, not a rule.

    The migration out of the old `reach` prose claims that no control moved,
    and the only thing that can catch a silent move is a count taken before
    and after. S7 splits the nineteen OFF controls into the ones you reach on
    the device base and the ones you really do take a hand off for, so these
    numbers are meant to change -- deliberately, and in this file.
    """

    def census(self):
        out = {}
        for dev in devicemap.load_all():
            for g in dev.groups(bindable=True):
                out[g.tier] = out.get(g.tier, 0) + 1
        return out

    def test_the_tiers_are_where_the_old_wording_left_them(self):
        # thumb and index on the grip: 14.  middle, ring and pinky
        # stretching for it: 4.  let go of the device: 19.
        self.assertEqual({0: 14, 1: 4, 3: 19}, self.census())

    def test_the_guessed_ones_are_the_ones_still_to_do(self):
        # "needs letting go" covered both the device base and taking a hand
        # off entirely, so all nineteen are marked as what they are.
        guessed = [g.label for dev in devicemap.load_all()
                   for g in dev.groups(bindable=True)
                   if any(a.how == 'guessed' for a in g.access)]
        self.assertEqual(19, len(guessed))
        self.assertTrue(all(g.tier == 3 for dev in devicemap.load_all()
                            for g in dev.groups(bindable=True)
                            if any(a.how == 'guessed' for a in g.access)))


if __name__ == '__main__':
    unittest.main()
