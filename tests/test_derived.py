"""What falls out of the facts, rather than being written down.

Three things here, and they are the point of the whole rearrangement: whether
two controls can be worked at once, what a control is without the word for
it, and which ergonomic facts somebody actually answered for.

None of them is stored. A stored answer to any of the three goes stale the
moment the rig moves or the capture is redone, and nothing would say so.
"""

import unittest

import devicemap
import fake


def rig(*devices):
    """A profile over several devices, each `(slug, hand, {id: spots})`."""
    said = [{'slug': slug, 'hand': hand, 'access': access}
            for slug, hand, access in devices]
    return devicemap.Profile({'name': 'Test', 'device': said}, '<fake>')


def spot(part='stick', level='HOME', finger='thumb'):
    return {'part': part, 'level': level, 'finger': finger}


def controls(**named):
    """`(slug, hand, access)` for one device carrying these controls."""
    groups = [fake.group('button', [n], label=cid, id=cid)
              for n, cid in enumerate(named)]
    return groups, {cid: spots for cid, spots in named.items()}


class WorkingTwoAtOnce(unittest.TestCase):
    """The question a pile of capture files cannot answer, and the reason a
    profile exists at all."""

    def pair(self, one, two, hands=('right', 'right')):
        groups, access = controls(one=one, two=two)
        dev = fake.device(groups=groups, slug='rig-a')
        got = dev.under(rig(('rig-a', hands[0], access))).groups()
        return devicemap.compatible(got[0], got[1])

    def test_one_finger_cannot_be_in_two_places(self):
        self.assertFalse(self.pair([spot(finger='thumb')],
                                   [spot(finger='thumb')]))

    def test_two_fingers_in_the_same_grip_can(self):
        self.assertTrue(self.pair([spot(finger='thumb')],
                                  [spot(finger='index')]))

    def test_the_hand_cannot_be_in_two_postures_at_once(self):
        # Different fingers, but one wants the grip and the other wants the
        # hand off it. The finger is not the constraint; the hand is.
        self.assertFalse(self.pair([spot(level='HOME', finger='thumb')],
                                   [spot(part='stick_base', level='BASE',
                                         finger='index')]))

    def test_a_stretched_finger_is_still_the_same_grip(self):
        # EXTENDED is not a posture of its own: the hand has not moved, one
        # finger has. So a thumb on one thing and a pinky reaching for
        # another is one hand doing two things.
        self.assertTrue(self.pair([spot(level='EXTENDED', finger='pinky')],
                                  [spot(finger='thumb')]))

    def test_a_control_reachable_two_ways_uses_the_way_that_works(self):
        self.assertTrue(self.pair(
            [spot(finger='thumb'), spot(level='EXTENDED', finger='pinky')],
            [spot(finger='thumb')]))

    def test_off_the_grip_is_a_posture_and_excludes_the_grip(self):
        self.assertFalse(self.pair([spot(level='BASE', finger='index')],
                                   [spot(finger='thumb')]))

    def test_one_hand_is_on_one_device(self):
        # Same posture, different fingers, but one spot is on the stick and
        # the other on the throttle. The finger was never the whole answer.
        self.assertFalse(self.pair([spot(part='stick', finger='thumb')],
                                   [spot(part='throttle', finger='index')]))

    def test_no_finger_recorded_means_no_and_not_probably(self):
        # The nineteen controls the old wording called "needs letting go"
        # arrived with a level and no finger, so nothing can say whether two
        # of them are two fingers or one. A hard constraint answers no to
        # what it cannot establish; S7 puts the fingers in.
        blank = spot(part='panel', level='OFF', finger='')
        known = spot(part='panel', level='OFF', finger='index')
        self.assertFalse(self.pair([blank], [dict(blank)]))
        self.assertFalse(self.pair([blank], [known]))
        self.assertFalse(self.pair([known], [blank]))

    def test_a_control_nobody_placed_composes_with_nothing(self):
        self.assertFalse(self.pair([], [spot()]))

    def test_it_does_not_matter_which_way_round_you_ask(self):
        groups, access = controls(one=[spot(finger='thumb')],
                                  two=[spot(finger='index')])
        got = fake.device(groups=groups, slug='rig-a').under(
            rig(('rig-a', 'right', access))).groups()
        self.assertEqual(devicemap.compatible(got[0], got[1]),
                         devicemap.compatible(got[1], got[0]))


class AcrossTwoDevices(unittest.TestCase):
    """The case the old map could not even express, because `hand` sat in a
    capture file and a capture file is not a desk."""

    def hotas(self, stick_hand='right', throttle_hand='left'):
        sg, sa = controls(trigger=[spot(part='stick', finger='index')])
        tg, ta = controls(wep=[spot(part='throttle', finger='index')])
        prof = rig(('a-stick', stick_hand, sa), ('a-throttle', throttle_hand, ta))
        stick = fake.device(groups=sg, slug='a-stick').under(prof)
        throttle = fake.device(groups=tg, slug='a-throttle').under(prof)
        return stick.groups()[0], throttle.groups()[0]

    def test_two_hands_do_two_things(self):
        a, b = self.hotas()
        self.assertTrue(devicemap.compatible(a, b))

    def test_both_bolted_under_one_hand_do_not(self):
        # Same index finger, two different devices. Nothing in either
        # capture file could have said so.
        a, b = self.hotas(throttle_hand='right')
        self.assertFalse(devicemap.compatible(a, b))


class WhatAControlIsWithoutTheWord(unittest.TestCase):
    """`kind` is what the person capturing it called the thing. `shape` is
    what it does, and it is what a rule should be written against."""

    def test_a_hat_that_clicks(self):
        got = fake.control('hat4', [4, 5, 6, 7], push=3,
                           dirs=['up', 'right', 'down', 'left']).shape
        self.assertEqual(4, got.positions)
        self.assertTrue(got.directional)
        self.assertTrue(got.clicks)
        self.assertFalse(got.latching)

    def test_a_staged_trigger(self):
        got = fake.control('trigger', [2, 3, 4], cumulative=True,
                           stages=['first', 'second', 'third']).shape
        self.assertEqual(3, got.positions)
        self.assertTrue(got.stepped)
        self.assertFalse(got.directional)

    def test_a_switch_that_stays_where_you_put_it(self):
        self.assertTrue(fake.control('switch2', [1, 2]).shape.latching)

    def test_a_mini_stick_is_two_axes_and_a_press(self):
        got = fake.control('ministick', [], push=5, axes=[3, 4]).shape
        self.assertEqual(2, got.axes)
        self.assertTrue(got.clicks)
        self.assertEqual(0, got.positions)

    def test_the_contacts_are_not_positions(self):
        # A rest contact is not somewhere you can put the control, so it
        # must not count towards how much room the control has.
        got = fake.control('trigger', [2, 3], rest_contact=1,
                           travel_contact=8, transient=[9]).shape
        self.assertEqual(2, got.positions)

    def test_the_word_is_not_consulted(self):
        # The same states under a different name describe the same thing.
        honest = fake.control('hat4', [4, 5, 6, 7],
                              dirs=['up', 'right', 'down', 'left']).shape
        mislabelled = fake.control('button', [4, 5, 6, 7],
                                   dirs=['up', 'right', 'down', 'left']).shape
        self.assertEqual(honest, mislabelled)


class WhoAnsweredForThis(unittest.TestCase):
    """A file that writes down its own guesses cannot say afterwards which
    ones they were, so a guess is never written down."""

    def test_an_answer_in_the_file_wins(self):
        g = fake.control('hat4', [1, 2], hold_ok=True)
        self.assertTrue(g.fact('hold_ok'))
        self.assertEqual('measured', g.told('hold_ok'))

    def test_otherwise_the_shape_answers(self):
        # A hat springs back, so holding one is not comfortable.
        g = fake.control('hat4', [1, 2])
        self.assertFalse(g.fact('hold_ok'))
        self.assertEqual('guessed', g.told('hold_ok'))

    def test_false_is_an_answer_like_any_other(self):
        # The trap in using a falsy default as "nobody said": a button is
        # held comfortably by default, and saying it is not must survive.
        g = fake.control('button', [1], hold_ok=False)
        self.assertFalse(g.fact('hold_ok'))
        self.assertEqual('measured', g.told('hold_ok'))

    def test_an_unwired_button_is_good_for_nothing(self):
        g = fake.control('unwired', [1, 2])
        self.assertFalse(g.fact('modifier_ok'))
        self.assertEqual('none', g.fact('blind_distinct'))

    def test_a_shape_nobody_tabulated(self):
        g = fake.control('something-new', [1])
        self.assertEqual('low', g.fact('accident_risk'))
        self.assertEqual('guessed', g.told('accident_risk'))

    def test_every_tabulated_shape_answers_every_fact(self):
        for kind, said in devicemap.DEFAULTS.items():
            with self.subTest(kind=kind):
                self.assertEqual(set(devicemap.NO_FACTS), set(said))


class TheDirectionVocabulary(unittest.TestCase):
    def test_the_captures_speak_it(self):
        # A rule that has to accept "forward" from one capture and "up" from
        # another is a rule about spelling.
        for dev in devicemap.load_all():
            for g in dev.groups():
                for st in g.states:
                    if not st.direction:
                        continue
                    with self.subTest(dev=dev.slug, ctrl=g.label):
                        self.assertIn(st.direction, devicemap.DIRECTIONS)


if __name__ == '__main__':
    unittest.main()
