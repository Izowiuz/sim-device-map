"""Which group owns which button.

`reconcile` promises one thing -- every button belongs to exactly one group --
and two functions answer "which buttons does this group own": `capture.all_of`
over the raw dict, `devicemap.Group.all_buttons` over the parsed one. They are
the same question, so they have to give the same answer, and the tests here
are mostly about the places they could stop doing that.

A button that falls out of the bookkeeping does not read as missing. It reads
as free, and the wizard offers it for something that is already wired.
"""

import unittest

import capture
import devicemap
import fake


class WhatAGroupOwns(unittest.TestCase):
    """`all_of` and `all_buttons`, side by side, on every field there is."""

    def both(self, g):
        """(raw answer, parsed answer) for one group dict."""
        return (sorted(capture.all_of(g)),
                sorted(devicemap.Group(**g).all_buttons))

    def test_plain_buttons(self):
        raw, parsed = self.both(fake.group('hat4', [4, 5, 6, 7]))
        self.assertEqual([4, 5, 6, 7], raw)
        self.assertEqual(raw, parsed)

    def test_a_hat_that_clicks(self):
        raw, parsed = self.both(fake.group('hat4', [4, 5, 6, 7], push=3))
        self.assertIn(3, raw)
        self.assertEqual(raw, parsed)

    def test_a_contact_closed_at_rest(self):
        raw, parsed = self.both(fake.group('trigger', [2, 3], rest_contact=1))
        self.assertIn(1, raw)
        self.assertEqual(raw, parsed)

    def test_contacts_that_fire_on_the_way_past(self):
        raw, parsed = self.both(fake.group('trigger', [2, 3], transient=[9]))
        self.assertIn(9, raw)
        self.assertEqual(raw, parsed)

    def test_a_contact_held_through_a_levers_travel(self):
        # The one that disagreed. A lever whose switch closes for almost all
        # of its travel is one physical control with the lever, and the raw
        # side never counted it.
        raw, parsed = self.both(fake.group('lever', [], travel_contact=31))
        self.assertIn(31, parsed)
        self.assertEqual(raw, parsed)


    def test_a_hat_records_which_way_each_position_points(self):
        # The name is what a person calls it; the direction is the fact an
        # algorithm can act on. A trigger's detents have a name and point
        # nowhere, which is why the two are not one field.
        hat = fake.control('hat4', [4, 5, 6, 7],
                           dirs=['up', 'right', 'down', 'left'])
        self.assertEqual(['up', 'right', 'down', 'left'],
                         [st.direction for st in hat.places])
        trig = fake.control('trigger', [2, 3], stages=['first', 'second'])
        self.assertEqual(['', ''], [st.direction for st in trig.places])

    def test_a_control_that_stays_put_says_so(self):
        for kind in devicemap.LATCHING:
            with self.subTest(kind=kind):
                g = fake.control(kind, [1, 2])
                self.assertTrue(all(st.latching for st in g.places))
        self.assertFalse(any(st.latching
                             for st in fake.control('hat4', [1, 2]).places))


class ReorderingAControl(unittest.TestCase):
    """Pressing a hat's directions back into order is an edit, not a
    recapture, so it must not cost the control anything else it owns."""

    def test_the_click_stays(self):
        g = fake.group('hat4', [4, 5, 6, 7], push=3)
        capture.set_buttons(g, [7, 6, 5, 4], ['up', 'right', 'down', 'left'])
        got = devicemap.Group(**g)
        self.assertEqual(3, got.push)
        self.assertEqual([7, 6, 5, 4], got.buttons)
        self.assertEqual('up', got.direction(7))

    def test_a_latching_control_stays_latching(self):
        g = fake.group('switch3', [1, 2])
        capture.set_buttons(g, [2, 1])
        self.assertTrue(all(st.latching
                            for st in devicemap.Group(**g).places))

class TheShapeOfAControl(unittest.TestCase):
    """`states_of` is the only place that says what a position looks like.

    It used to be two: the wizard built one shape and a converter folded
    it into another. These are the rules that converter was holding.
    """

    def test_a_contact_a_control_holds_is_written_as_held(self):
        got = capture.states_of('trigger', [2, 3], ['first', 'second'],
                                contacts=[('rest', 9), ('travel', 10)])
        held = {st['button']: st.get('latching') for st in got}
        self.assertTrue(held[9])
        self.assertTrue(held[10])

    def test_a_click_is_not_held(self):
        got, = capture.states_of('hat4', [], contacts=[('push', 9)])
        self.assertFalse(got.get('latching'))

    def test_a_switch_that_stays_put_holds_every_position(self):
        got = capture.states_of('switch2', [4, 5])
        self.assertTrue(all(st.get('latching') for st in got))

    def test_a_direction_is_a_name_that_points_somewhere(self):
        got = capture.states_of('hat4', [4, 5], ['up', 'right'],
                                directional=True)
        self.assertEqual(['up', 'right'], [st['direction'] for st in got])
        self.assertEqual(['up', 'right'], [st['name'] for st in got])

    def test_a_stage_is_a_name_that_does_not(self):
        got = capture.states_of('trigger', [2, 3], ['first', 'second'])
        self.assertEqual(['first', 'second'], [st['name'] for st in got])
        self.assertTrue(all('direction' not in st for st in got))

    def test_the_positions_come_before_what_else_it_closes(self):
        got = capture.states_of('trigger', [2, 3], contacts=[('rest', 9)])
        self.assertEqual([2, 3, 9], [st['button'] for st in got])

    def test_a_reorder_does_not_hand_a_trigger_directions(self):
        g = fake.group('trigger', [2, 3], stages=['first', 'second'])
        capture.set_buttons(g, [3, 2], ['first', 'second'])
        self.assertTrue(all('direction' not in st for st in g['states']))

    def test_a_reorder_keeps_a_hat_pointing(self):
        g = fake.group('hat2', [4, 5], dirs=['up', 'down'])
        capture.set_buttons(g, [5, 4], ['down', 'up'])
        self.assertEqual(['down', 'up'],
                         [st['direction'] for st in g['states']])


class TheUnknownBucket(unittest.TestCase):
    """What `reconcile` sweeps up, and what it must not."""

    def test_an_uncaptured_button_goes_in(self):
        data = fake.raw(groups=[fake.group('button', [0])], buttons=3)
        missing = capture.reconcile(data, 3)
        self.assertEqual([1, 2], missing)
        bucket = next(g for g in data['group'] if g['kind'] == 'unknown')
        self.assertEqual([1, 2], capture.buttons_of(bucket))

    def test_the_bucket_goes_away_when_it_empties(self):
        data = fake.raw(groups=[fake.group('button', [0]),
                                fake.group('unknown', [1])], buttons=1)
        capture.reconcile(data, 1)
        self.assertEqual([], [g for g in data['group']
                              if g['kind'] == 'unknown'])

    def test_a_click_is_not_swept_up(self):
        data = fake.raw(groups=[fake.group('hat4', [0, 1, 2, 3], push=4)],
                        buttons=5)
        self.assertEqual([], capture.reconcile(data, 5))

    def test_a_travel_contact_is_not_swept_up(self):
        # This is the bug: the lever owns button 1, `all_of` did not say so,
        # and the button came back as free while `group_of(1)` still found
        # the lever. Two groups, one button, and the wizard offering a
        # control that is already wired.
        data = fake.raw(groups=[fake.group('lever', [0], travel_contact=1)],
                        buttons=2)
        self.assertEqual([], capture.reconcile(data, 2))
        self.assertEqual([], [g for g in data['group']
                              if g['kind'] == 'unknown'])

    def test_nothing_ends_up_in_two_groups(self):
        # The invariant itself, asked of the parsed side, which is the side
        # every consumer reads.
        data = fake.raw(groups=[fake.group('lever', [0], travel_contact=1),
                                fake.group('button', [2])], buttons=4)
        capture.reconcile(data, 4)
        dev = devicemap.Device(data, '<fake>')
        owners = {}
        for g in dev.groups():
            for b in g.all_buttons:
                owners.setdefault(b, []).append(g.label or g.kind)
        twice = {b: who for b, who in owners.items() if len(who) > 1}
        self.assertEqual({}, twice)


class WhatCanBeBound(unittest.TestCase):
    """`bindable_buttons` is the allocator's whole notion of how much room a
    control has, so what it leaves out matters as much as what it keeps."""

    def test_a_click_can_be_bound(self):
        g = fake.control('hat4', [4, 5, 6, 7], push=3)
        self.assertEqual([4, 5, 6, 7, 3], g.bindable_buttons)

    def test_the_contacts_cannot(self):
        g = fake.control('trigger', [2, 3], rest_contact=1,
                         travel_contact=8, transient=[9])
        self.assertEqual([2, 3], g.bindable_buttons)

    def test_a_bucket_offers_nothing(self):
        for kind in ('unknown', 'unwired', 'switch-position'):
            with self.subTest(kind=kind):
                g = fake.control(kind, [0, 1])
                self.assertEqual([], g.bindable_buttons)
                self.assertFalse(g.bindable)


class WhatAButtonIsCalled(unittest.TestCase):
    """`direction()` is read at 27 call sites in the other repo; it is the
    only thing that turns a button number back into a word."""

    def test_a_hat_names_its_directions(self):
        g = fake.control('hat4', [4, 5, 6, 7],
                         dirs=['up', 'right', 'down', 'left'])
        self.assertEqual(['up', 'right', 'down', 'left'],
                         [g.direction(b) for b in (4, 5, 6, 7)])

    def test_a_trigger_names_its_stages(self):
        g = fake.control('trigger', [2, 3, 4],
                         stages=['first', 'second', 'third'])
        self.assertEqual('second', g.direction(3))

    def test_the_click_is_called_push(self):
        g = fake.control('hat4', [4, 5, 6, 7], push=3,
                         dirs=['up', 'right', 'down', 'left'])
        self.assertEqual('push', g.direction(3))

    def test_a_contact_says_what_it_is(self):
        # These words reach a screen in the repo that reads this map. A
        # contact named after its role rather than its consequence reads as
        # a place you can put the control, which is exactly what it is not.
        g = fake.control('trigger', [2, 3], rest_contact=1,
                         travel_contact=8, transient=[9])
        self.assertEqual('rest contact (inverted)', g.direction(1))
        self.assertIn('held while the lever is used', g.direction(8))
        self.assertIn('fires both ways', g.direction(9))

    def test_a_plain_button_has_no_word_for_where_it_is(self):
        # Not a list of empty strings: every caller asks whether there are
        # names at all before it asks what they are, and one blank passes
        # that question.
        self.assertEqual([], fake.control('button', [0]).names)
        self.assertEqual([], fake.control('button', [0]).dirs)

    def test_a_button_the_group_does_not_own(self):
        # Empty rather than None: every caller writes `direction(b) or ...`,
        # and a name that is falsy is one fewer thing for them to check.
        g = fake.control('button', [0])
        self.assertEqual('', g.direction(7))


if __name__ == '__main__':
    unittest.main()
