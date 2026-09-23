"""From a control to its answers and back.

`_already` reads a captured control as the answers that would have produced
it; `build_group` turns answers back into a control. Between them they are
what makes editing the same walk as capturing, and a control that does not
survive the trip is a control the wizard quietly rewrites.

The real captures are the fixtures, because they are the shapes that exist.
"""

import copy
import os
import shutil
import struct
import tempfile
import unittest

import capture
import devicemap
import fake
import questions as q
import screens
import tui


def round_trip(group):
    """The group a finished walk would write, starting from this one."""
    run = q.Run(capture.SHEET, given=capture._already(group))
    return devicemap.Group(**capture.build_group(run, group))


class EveryCapturedControlSurvivesTheTrip(unittest.TestCase):
    def controls(self):
        """Every control the wizard can actually capture.

        A lever that is an axis plus a travel contact owns no positions at
        all, and nothing in the descriptor asks about one: it is not a shape
        you press. Left out here rather than asserted about falsely.
        """
        shapes = {c['name'] for c in capture.SHEET.vocabulary['kind']}
        for dev in fake.devices():
            for g in dev.groups(bindable=True):
                if g.kind in shapes:
                    yield dev, g

    def test_the_fixtures_are_not_empty(self):
        self.assertTrue(list(self.controls()))

    def test_it_keeps_its_buttons(self):
        for dev, g in self.controls():
            with self.subTest(dev=dev.slug, ctrl=g.label):
                self.assertEqual(g.buttons, round_trip(g).buttons)

    def test_it_keeps_its_click(self):
        for dev, g in self.controls():
            with self.subTest(dev=dev.slug, ctrl=g.label):
                self.assertEqual(g.push, round_trip(g).push)

    def test_it_keeps_what_its_positions_are_called(self):
        for dev, g in self.controls():
            with self.subTest(dev=dev.slug, ctrl=g.label):
                self.assertEqual(g.names, round_trip(g).names)

    def test_it_keeps_the_axes_it_owns(self):
        # Nothing in the walk asks about them, so nothing in the walk may
        # drop them: a mini-stick is two axes and a press, and the press is
        # the only part it was asked about.
        for dev, g in self.controls():
            with self.subTest(dev=dev.slug, ctrl=g.label):
                self.assertEqual(g.axes, round_trip(g).axes)

    def test_it_keeps_its_name_and_its_id(self):
        for dev, g in self.controls():
            with self.subTest(dev=dev.slug, ctrl=g.label):
                got = round_trip(g)
                self.assertEqual(g.label, got.label)
                self.assertEqual(g.id, got.id)

    def test_it_keeps_every_button_it_owns(self):
        # Not just the positions: a contact that falls out here is a button
        # handed back as free while the control still claims it.
        for dev, g in self.controls():
            with self.subTest(dev=dev.slug, ctrl=g.label):
                self.assertEqual(sorted(g.all_buttons),
                                 sorted(round_trip(g).all_buttons))

    def test_a_control_already_answered_for_asks_nothing(self):
        for dev, g in self.controls():
            run = q.Run(capture.SHEET, given=capture._already(g))
            with self.subTest(dev=dev.slug, ctrl=g.label):
                self.assertTrue(run.done, run.next())


class BuildingOneFromAnswers(unittest.TestCase):
    def built(self, **given):
        run = q.Run(capture.SHEET, given=given)
        return devicemap.Group(**capture.build_group(run))

    def test_a_hat_with_a_click(self):
        got = self.built(buttons=([8, 11, 10, 9, 7], set()), kind='hat4',
                         click=7, order=[8, 11, 10, 9], name='Top hat')
        self.assertEqual([8, 11, 10, 9], got.buttons)
        self.assertEqual(7, got.push)
        self.assertEqual(['up', 'right', 'down', 'left'], got.names)

    def test_a_staged_trigger(self):
        got = self.built(buttons=([2, 3, 4, 1], set()), kind='trigger',
                         pull={'stages': [2, 3, 4], 'rest': 1,
                               'transient': [], 'cumulative': True},
                         returns='yes', name='Main trigger')
        self.assertEqual([2, 3, 4], got.buttons)
        self.assertEqual(1, got.contact('rest'))
        self.assertTrue(got.cumulative)

    def test_a_lever_pushed_back_by_hand_is_not_a_rest_contact(self):
        # Timing cannot tell the two apart, so the answer decides. Saying no
        # has to actually drop it, or a latching lever ends up recorded as
        # part of the trigger it sits next to.
        got = self.built(buttons=([2, 3, 1], set()), kind='trigger',
                         pull={'stages': [2, 3], 'rest': 1, 'transient': [],
                               'cumulative': True},
                         returns='no', name='Main trigger')
        self.assertIsNone(got.contact('rest'))

    def test_a_rocker_takes_the_directions_it_was_told(self):
        got = self.built(buttons=([10, 12], set()), kind='hat2',
                         which_way='fwd_aft', order=[10, 12], name='Rocker')
        self.assertEqual(['fwd', 'aft'], got.names)

    def test_a_plain_button_has_nothing_to_say_about_directions(self):
        got = self.built(buttons=([6], set()), kind='button', name='Pinky')
        self.assertEqual([], got.names)
        self.assertEqual([6], got.buttons)


class WritingTheRigBack(unittest.TestCase):
    """The wizard measures reach and has to put it somewhere. Until now
    nothing in this repo could write a profile at all."""

    def rewritten(self, prof):
        """A profile through the writer, parsed back."""
        import shutil
        import tempfile
        import tomllib
        with tempfile.TemporaryDirectory() as box:
            dst = os.path.join(box, os.path.basename(prof.path))
            shutil.copy(prof.path, dst)
            with open(dst, 'rb') as fh:
                again = devicemap.Profile(tomllib.load(fh), dst)
            capture.write_profile(again)
            with open(dst, 'rb') as fh:
                return tomllib.load(fh), open(dst).read()

    def test_nothing_is_lost(self):
        for prof in devicemap.load_profiles():
            back, _text = self.rewritten(prof)
            with self.subTest(rig=prof.name):
                self.assertEqual(_facts(prof._as_dict()), _facts(back))

    def test_prose_above_the_first_field_is_kept(self):
        # Nothing regenerates it: it is what somebody wrote about their
        # own desk. A desk with none written about it has none to keep.
        for prof in devicemap.load_profiles():
            head = open(prof.path).read().lstrip()
            if not head.startswith('#'):
                continue
            _back, text = self.rewritten(prof)
            with self.subTest(rig=prof.name):
                self.assertTrue(text.lstrip().startswith('#'), text[:40])
                self.assertIn(head.splitlines()[0], text)

    def test_a_measured_spot_says_nothing_about_being_measured(self):
        # `how` is only worth a column when it is not the ordinary case.
        for prof in devicemap.load_profiles():
            _back, text = self.rewritten(prof)
            with self.subTest(rig=prof.name):
                self.assertNotIn('"measured"', text)

    def test_a_guess_in_the_rig_on_file_says_so(self):
        for prof in devicemap.load_profiles():
            guessed = any(sp.get('how') == 'guessed'
                          for d in prof.devices
                          for spots in (d.get('access') or {}).values()
                          for sp in spots)
            if not guessed:
                continue
            _back, text = self.rewritten(prof)
            with self.subTest(rig=prof.name):
                self.assertIn('"guessed"', text)


class WhatTheRoundsAmountTo(unittest.TestCase):
    """Reach measured by reaching: each round is a posture and a finger,
    and what the rounds say about a control is where it ends up."""

    def dev(self):
        return fake.devices()[0]

    def some(self, dev, n=2):
        return [g for g in dev.groups(bindable=True) if g.id][:n]

    def test_a_control_pressed_in_a_round_gets_that_posture(self):
        dev = self.dev()
        one = self.some(dev, 1)[0]
        got = capture.reach_from(dev, [('HOME', 'thumb', one.buttons[:1])])
        self.assertEqual([{'part': dev.kind, 'level': 'HOME',
                           'finger': 'thumb'}], got[one.id])

    def test_reached_two_ways_is_recorded_two_ways(self):
        dev = self.dev()
        one = self.some(dev, 1)[0]
        got = capture.reach_from(dev, [('HOME', 'thumb', one.buttons[:1]),
                                       ('BASE', 'index', one.buttons[:1])])
        self.assertEqual(2, len(got[one.id]))

    def test_what_you_never_pressed_is_off_the_device(self):
        # Not left out. A control missing from the rounds is one you take
        # your hand off for, and saying nothing leaves it looking unmeasured.
        dev = self.dev()
        got = capture.reach_from(dev, [])
        placed = [g for g in dev.groups(bindable=True) if g.id]
        self.assertEqual(len(placed), len(got))
        self.assertTrue(all(sp[0]['level'] == 'OFF' for sp in got.values()))

    def test_every_control_you_can_bind_ends_up_somewhere(self):
        dev = self.dev()
        one = self.some(dev, 1)[0]
        got = capture.reach_from(dev, [('HOME', 'thumb', one.buttons[:1])])
        for g in dev.groups(bindable=True):
            if g.id:
                with self.subTest(ctrl=g.label):
                    self.assertTrue(got.get(g.id))

    def test_a_button_nothing_owns_is_ignored(self):
        dev = self.dev()
        got = capture.reach_from(dev, [('HOME', 'thumb', [9999])])
        self.assertTrue(all(sp[0]['level'] == 'OFF' for sp in got.values()))


class HowASpotIsWritten(unittest.TestCase):
    def test_a_spot_writes_every_part_of_itself(self):
        # The one the wizard actually hands it: a `Spot`, not a dict.
        import tomllib
        spot = devicemap.Spot(part='stick', level='HOME', finger='thumb')
        got = tomllib.loads('x = ' + capture._spot_said(spot))['x']
        self.assertEqual({'part': 'stick', 'level': 'HOME',
                          'finger': 'thumb'}, got)

    def test_no_finger_recorded_writes_no_finger(self):
        said = capture._spot_said({'part': 'panel', 'level': 'OFF',
                                   'finger': ''})
        self.assertNotIn('finger', said)

    def test_it_parses_as_what_it_claims_to_be(self):
        import tomllib
        got = tomllib.loads('x = ' + capture._spot_said(
            {'part': 'stick', 'level': 'HOME', 'finger': 'thumb'}))
        self.assertEqual({'part': 'stick', 'level': 'HOME',
                          'finger': 'thumb'}, got['x'])


class WhereAHandIsAtEachLevel(unittest.TestCase):
    def test_in_the_grip_it_is_on_the_device(self):
        dev = fake.devices()[0]
        for level in devicemap.GRIPPED:
            with self.subTest(level=level):
                self.assertEqual(dev.kind, capture._part_of(dev, level))

    def test_off_the_grip_it_is_on_the_base(self):
        dev = fake.devices()[0]
        self.assertEqual(f'{dev.kind}_base', capture._part_of(dev, 'BASE'))

    def test_every_part_it_names_is_in_the_vocabulary(self):
        for dev in fake.devices():
            for level in devicemap.LEVELS[:3]:
                with self.subTest(dev=dev.slug, level=level):
                    self.assertIn(capture._part_of(dev, level),
                                  devicemap.PARTS)


class RecordingAFact(unittest.TestCase):
    def test_it_reaches_the_file_and_the_thing_in_hand(self):
        # Both, because the screen redraws from the parsed control and the
        # writer emits from the raw one. Setting only the first loses it on
        # save; only the second and the list still says "to go".
        dev = fake.devices()[0]
        g = next(x for x in dev.groups(bindable=True) if x.id)
        capture._set_fact(dev, g, 'hold_ok', False)
        try:
            self.assertEqual('measured', g.told('hold_ok'))
            raw = next(r for r in dev._raw['group'] if r.get('id') == g.id)
            self.assertIs(False, raw['hold_ok'])
        finally:
            g.hold_ok = None
            raw = next(r for r in dev._raw['group'] if r.get('id') == g.id)
            raw.pop('hold_ok', None)


def _facts(data):
    """A rig with the orderings that do not matter taken out."""
    return {'name': data.get('name'),
            'device': sorted(
                ({k: (v if k != 'access'
                      else {c: tuple(tuple(sorted(sp.items())) for sp in spots)
                            for c, spots in v.items()})
                  for k, v in dev.items()}
                 for dev in data.get('device', [])),
                key=lambda d: str(d['slug']))}


class AControlThatOwnsNothing(unittest.TestCase):
    """RETURN with nothing pressed used to be taken as an answer, and the
    answer it made was a control with no buttons: a row in the list with
    no name and no way ever to give it one."""

    def dev(self):
        import copy
        real = fake.devices()[0]
        return devicemap.Device(copy.deepcopy(real._raw), real.path)

    def empty(self):
        run = q.Run(capture.SHEET, given={'buttons': ([], set()),
                                          'kind': 'button', 'name': ''})
        return capture.build_group(run)

    def test_it_is_refused(self):
        dev = self.dev()
        before = len(dev._raw['group'])
        self.assertFalse(capture._replace(dev, None, self.empty()))
        self.assertEqual(before, len(dev._raw['group']))

    def test_a_control_with_only_axes_is_not_empty(self):
        dev = self.dev()
        entry = dict(self.empty(), axes=[5], kind='ministick')
        self.assertTrue(capture._replace(dev, None, entry))

    def test_a_control_with_only_a_click_is_not_empty(self):
        dev = self.dev()
        run = q.Run(capture.SHEET, given={'buttons': ([44], set()),
                                          'kind': 'dial', 'click': 44,
                                          'name': 'A dial'})
        self.assertTrue(capture._replace(dev, None,
                                         capture.build_group(run)))

    def test_an_ordinary_one_goes_in(self):
        # Counting the groups would not say it: taking a button off
        # whatever had it can remove a group in the same breath.
        dev = self.dev()
        run = q.Run(capture.SHEET, given={'buttons': ([45], set()),
                                          'kind': 'button', 'name': 'New'})
        self.assertTrue(capture._replace(dev, None,
                                         capture.build_group(run)))
        dev.__init__(dev._raw, dev.path)
        self.assertIn('New', [g.label for g in dev.groups()])
        got = dev.group_of(45)
        assert got is not None
        self.assertEqual([45], got.buttons)


class SteppingAnAnswerOn(unittest.TestCase):
    """The hardware is in your hands, so pressing a control is how you
    answer about it. One gesture for both shapes of question."""

    def setUp(self):
        import copy
        real = fake.devices()[0]
        self.dev = devicemap.Device(copy.deepcopy(real._raw), real.path)
        self.dev.under(fake.rig(real))
        self.g = next(x for x in self.dev.groups(bindable=True) if x.id)
        self.sheet = capture.SHEET

    def ask(self, sets):
        return next(a for a in self.sheet.of(q.ALL) if a.sets == sets)

    def walk(self, sets, times):
        ask = self.ask(sets)
        seen = []
        for _ in range(times):
            capture._step(self.dev, self.g, ask, self.sheet.choices(ask))
            seen.append(self.g.fact(sets))
        return seen

    def test_a_yes_or_no_starts_at_yes(self):
        self.assertIsNone(self.g.fact('hold_ok'))
        self.assertEqual([True], self.walk('hold_ok', 1))

    def test_it_walks_round_through_no_answer(self):
        # Round the end is unanswered, because a control you touched by
        # mistake has to be able to go back to it.
        self.assertEqual([True, False, None], self.walk('hold_ok', 3))

    def test_answering_makes_it_answered(self):
        ask = self.ask('hold_ok')
        self.assertEqual('missing', self.g.told('hold_ok'))
        capture._step(self.dev, self.g, ask, self.sheet.choices(ask))
        self.assertEqual('measured', self.g.told('hold_ok'))

    def test_a_graded_answer_walks_its_own_choices(self):
        picks = [c['name'] for c in self.sheet.choices(self.ask('blind_distinct'))]
        seen = self.walk('blind_distinct', len(picks) + 1)
        self.assertEqual(picks, seen[:len(picks)])
        self.assertIsNone(seen[-1])

    def test_it_only_ever_lands_on_a_choice_or_on_nothing(self):
        picks = [c['name'] for c in self.sheet.choices(self.ask('accident_risk'))]
        for got in self.walk('accident_risk', 9):
            self.assertIn(got, picks + [None])


class Said:
    """A tui that only remembers what it was told to show."""

    def __init__(self):
        self.shown = []

    def popup(self, title, lines, full=False):
        self.shown.append((title, [t for _tone, t in lines]))


class Browsed:
    """A tui that answers the reach list with ESC and keeps the call."""

    def __init__(self):
        self.kw = {}

    def browse(self, title, lines, side, **kw):
        self.kw = dict(kw, title=title, lines=lines, side=side)
        return None, 0


class TheReachListIsNotCountedInRows(unittest.TestCase):

    def test_the_panel_counts_nothing_rather_than_rows(self):
        # Three of the rows are postures, so a row count would disagree
        # with the round count on the other half of the same frame.
        dev = fake.devices()[0]
        prof = fake.rig(dev)
        tui = Browsed()
        capture.ask_reach(tui, None, dev, prof)
        count = tui.kw.get('count')
        assert count is not None
        self.assertEqual('', count(0))


class WhatNoRoundReached(unittest.TestCase):
    """Whatever none of the rounds reached is something you take a hand
    off the device for -- but only once every round has been walked."""

    def test_it_says_what_it_worked_out_rather_than_just_writing_it(self):
        # The one answer on that screen nobody gave by pressing
        # something. Written in silence it looks like data from nowhere.
        dev = fake.devices()[0]
        tui, said = Said(), {'access': {}}
        capture._hands_off(tui, dev, said)
        self.assertEqual(1, len(tui.shown))
        title, lines = tui.shown[0]
        for t in [title] + lines:            # the word nobody understood
            with self.subTest(said=t):
                self.assertNotRegex(t.lower(), r'\bround')
        for g in dev.groups(bindable=True):
            if g.id:
                with self.subTest(ctrl=g.id):
                    self.assertTrue(any((g.label or g.kind) in t
                                        for t in lines))

    def test_it_stays_quiet_when_every_control_was_reached(self):
        dev = fake.devices()[0]
        mine = [{'part': 'throttle', 'level': 'HOME', 'finger': 'thumb'}]
        said = {'access': {g.id: list(mine)
                           for g in dev.groups(bindable=True) if g.id}}
        tui = Said()
        capture._hands_off(tui, dev, said)
        self.assertEqual([], tui.shown)

    def test_a_control_nobody_reached_ends_up_off(self):
        dev = fake.devices()[0]
        said = {'access': {}}
        capture._hands_off(Said(), dev, said)
        every = [g.id for g in dev.groups(bindable=True) if g.id]
        self.assertEqual(sorted(every), sorted(said['access']))
        self.assertTrue(all(sp[0]['level'] == 'OFF'
                            for sp in said['access'].values()))

    def test_one_that_was_reached_is_left_alone(self):
        dev = fake.devices()[0]
        one = next(g for g in dev.groups(bindable=True) if g.id)
        mine = [{'part': 'throttle', 'level': 'HOME', 'finger': 'thumb'}]
        said = {'access': {one.id: list(mine)}}
        capture._hands_off(Said(), dev, said)
        self.assertEqual(mine, said['access'][one.id])

    def test_nothing_that_cannot_be_bound_is_placed(self):
        dev = fake.devices()[0]
        said = {'access': {}}
        capture._hands_off(Said(), dev, said)
        for g in dev.groups():
            if not g.bindable and g.id:
                with self.subTest(ctrl=g.id):
                    self.assertNotIn(g.id, said['access'])


class FindingTheButtonYouPicked(unittest.TestCase):
    """Picking `js 19` off the list tells you a number and nothing about
    which piece of plastic it is."""

    def test_the_one_you_picked_says_so(self):
        tone, said = capture._pressed(19, 19)
        self.assertEqual('measured', tone)
        self.assertIn('that one', said)
        self.assertIn('19', said)

    def test_any_other_says_it_is_another(self):
        tone, said = capture._pressed(4, 19)
        self.assertNotEqual('measured', tone)
        self.assertIn('different', said)
        self.assertIn('4', said)

    def test_the_two_do_not_read_alike(self):
        self.assertNotEqual(capture._pressed(19, 19),
                            capture._pressed(4, 19))

    def test_with_nothing_picked_it_just_says_the_button(self):
        _tone, said = capture._pressed(4, None)
        self.assertNotIn('different', said)
        self.assertNotIn('that one', said)
        self.assertIn('4', said)


class SteppingBack(unittest.TestCase):
    def test_from_the_second_question_you_land_on_the_first(self):
        run = q.Run(capture.SHEET)
        run.answer(run.by_id['buttons'], ([6], set()))
        self.assertEqual('buttons', capture._before(run, run.by_id['kind']))

    def test_from_the_first_there_is_nowhere_to_go(self):
        run = q.Run(capture.SHEET)
        first = run.next()
        assert first is not None
        self.assertEqual(first.id, capture._before(run, first))

    def test_it_skips_what_this_shape_never_asked(self):
        run = q.Run(capture.SHEET, given={'buttons': ([6], set()),
                                          'kind': 'button'})
        self.assertEqual('kind', capture._before(run, run.by_id['name']))


if __name__ == '__main__':
    unittest.main()


class WhatMovedTogether(unittest.TestCase):
    """The question the trace exists to answer.

    "Free in the plan" and "free under the hand" are different: a trim
    axis on a throttle lever that travels under the same hand trims the
    aircraft on every power change, and nothing in the map said so.
    """

    def moved(self, events):
        return capture.what_moved_together(events)

    def test_a_lever_whose_travel_ends_in_a_switch(self):
        got, = self.moved([(1.00, 'axis', 5, 12000),
                           (1.10, 'button', 31, 1)])
        self.assertEqual(('contact', 31, 5), (got.kind, got.a, got.b))

    def test_a_press_long_after_the_travel_is_a_separate_control(self):
        self.assertEqual([], self.moved([(1.0, 'axis', 5, 12000),
                                         (9.0, 'button', 31, 1)]))

    def test_a_release_is_not_a_press(self):
        self.assertEqual([], self.moved([(1.0, 'axis', 5, 12000),
                                         (1.1, 'button', 31, 0)]))

    def test_two_levers_clamped_into_one(self):
        got, = self.moved([(1.000, 'axis', 2, 8000),
                           (1.005, 'axis', 3, 8000)])
        self.assertEqual(('axes', 2, 3), (got.kind, got.a, got.b))

    def test_two_levers_that_happen_to_pass_the_same_value(self):
        # Far enough apart in time to be two hands doing two things.
        self.assertEqual([], self.moved([(1.0, 'axis', 2, 8000),
                                         (3.0, 'axis', 3, 8000)]))

    def test_the_same_axis_twice_is_not_a_pair(self):
        self.assertEqual([], self.moved([(1.000, 'axis', 2, 8000),
                                         (1.005, 'axis', 2, 8000)]))

    def test_a_pair_is_named_the_same_way_round_every_time(self):
        one, = self.moved([(1.000, 'axis', 3, 8000),
                           (1.005, 'axis', 2, 8000)])
        two, = self.moved([(1.000, 'axis', 2, 8000),
                           (1.005, 'axis', 3, 8000)])
        self.assertEqual((one.a, one.b), (two.a, two.b))

    def test_the_one_that_kept_happening_comes_first(self):
        events = [(1.000, 'axis', 2, 8000), (1.005, 'axis', 3, 8000),
                  (2.000, 'axis', 2, 9000), (2.005, 'axis', 3, 9000),
                  (5.000, 'axis', 6, 100), (5.010, 'axis', 7, 100)]
        first, second = self.moved(events)
        self.assertGreater(first.times, second.times)
        self.assertEqual((2, 3), (first.a, first.b))

    def test_nothing_at_all_is_not_an_answer_about_anything(self):
        self.assertEqual([], self.moved([]))


class WritingDownACoupling(unittest.TestCase):
    """Two axes that move as one, recorded on both of them.

    `moves_with` and `coupling` have been in the schema since the start
    and nothing could ever fill them: they were typed into the file by
    hand. This is what fills them.
    """

    class Picks:
        """A tui that answers every menu with the same choice."""

        def __init__(self, pick: 'int | None' = 0):
            self.pick, self.asked = pick, []

        def menu(self, title, items, hints=None, subtitle='', **kw):
            self.asked.append((title, list(items), subtitle))
            return self.pick

    def setUp(self):
        real = fake.devices()[0]
        self.dev = devicemap.Device(copy.deepcopy(real._raw), real.path)
        for a in self.dev._raw['axis']:
            a.pop('moves_with', None)
            a.pop('coupling', None)
        self.dev = devicemap.Device(self.dev._raw, real.path)

    def moved(self, a=2, b=3, times=4):
        return [capture.Moved('axes', a, b, times)]

    def axis(self, index):
        got = self.dev.axis(index)
        assert got is not None
        return got

    def test_it_writes_the_pair_on_both_of_them(self):
        self.assertTrue(capture._record_couplings(
            self.Picks(), self.dev, self.moved()))
        self.assertEqual([3], self.axis(2).moves_with)
        self.assertEqual([2], self.axis(3).moves_with)

    def test_it_writes_what_kind_of_coupling_you_picked(self):
        capture._record_couplings(self.Picks(1), self.dev, self.moved())
        self.assertEqual(capture.COUPLINGS[1], self.axis(2).coupling)

    def test_it_reaches_the_file_and_the_thing_in_hand(self):
        capture._record_couplings(self.Picks(), self.dev, self.moved())
        raw = next(a for a in self.dev._raw['axis'] if a['index'] == 2)
        self.assertEqual([3], raw['moves_with'])
        self.assertEqual(self.axis(2).moves_with, raw['moves_with'])

    def test_saying_nothing_writes_nothing(self):
        self.assertFalse(capture._record_couplings(
            self.Picks(None), self.dev, self.moved()))
        self.assertEqual([], self.axis(2).moves_with)

    def test_a_button_during_a_travel_is_not_written_here(self):
        # That is a fact about one control -- a lever whose travel ends
        # in a switch -- and the place to say so is the control.
        tui = self.Picks()
        self.assertFalse(capture._record_couplings(
            tui, self.dev, [capture.Moved('contact', 31, 5, 3)]))
        self.assertEqual([], tui.asked)

    def test_the_question_names_the_two_levers_and_not_just_numbers(self):
        tui = self.Picks()
        capture._record_couplings(tui, self.dev, self.moved())
        _title, _items, subtitle = tui.asked[0]
        self.assertIn(self.axis(2).label, subtitle)
        self.assertIn(self.axis(3).label, subtitle)

    def test_a_pair_already_on_file_gains_rather_than_replaces(self):
        raw = next(a for a in self.dev._raw['axis'] if a['index'] == 2)
        raw['moves_with'] = [7]
        self.dev = devicemap.Device(self.dev._raw, self.dev.path)
        capture._record_couplings(self.Picks(), self.dev, self.moved())
        self.assertEqual([3, 7], self.axis(2).moves_with)


class WhatGetsIntoTheTrace(unittest.TestCase):
    """A trace of a stick jittering at rest is a trace of nothing with
    the real events pushed off the top of it."""

    def setUp(self):
        self.events, self.rest = [], {}

    def add(self, typ, num, val, now=1.0):
        return capture.add_event(self.events, self.rest, now, typ, num, val)

    def test_a_press_goes_in(self):
        self.assertTrue(self.add(capture.JS_EVENT_BUTTON, 3, 1))
        self.assertEqual([(1.0, 'button', 3, 1)], self.events)

    def test_a_release_goes_in_too(self):
        self.assertTrue(self.add(capture.JS_EVENT_BUTTON, 3, 0))

    def test_an_axis_parked_away_from_centre_has_not_moved(self):
        # Where the opening burst said it was sitting. Without this a
        # lever parked at one end opens the trace with a full-scale move
        # that nobody made.
        self.rest[2] = 9000
        self.assertFalse(self.add(capture.JS_EVENT_AXIS, 2, 9000))
        self.assertTrue(self.add(capture.JS_EVENT_AXIS, 2, 32000))

    def test_jitter_is_not_travel(self):
        self.assertFalse(self.add(capture.JS_EVENT_AXIS, 2,
                                  capture.AXIS_MOVED - 1))
        self.assertEqual([], self.events)

    def test_travel_is(self):
        self.assertTrue(self.add(capture.JS_EVENT_AXIS, 2,
                                 capture.AXIS_MOVED + 1))

    def test_travel_is_measured_from_where_it_last_was(self):
        self.add(capture.JS_EVENT_AXIS, 2, 20000)
        self.assertFalse(self.add(capture.JS_EVENT_AXIS, 2, 21000))
        self.assertTrue(self.add(capture.JS_EVENT_AXIS, 2, 30000))


class WhereTheAxesAreSittingWhenYouStart(unittest.TestCase):
    """The burst the driver sends on open, kept rather than thrown away."""

    def burst(self, events):
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b''.join(
            struct.pack('<IhBB', 0, val, typ, num) for typ, num, val in events))
        os.close(write_fd)
        try:
            return capture.axes_at_rest(read_fd)
        finally:
            os.close(read_fd)

    def test_it_reads_where_each_axis_is(self):
        got = self.burst([(capture.JS_EVENT_AXIS | capture.JS_EVENT_INIT,
                           2, 9000)])
        self.assertEqual({2: 9000}, got)

    def test_buttons_in_the_burst_are_not_axes(self):
        got = self.burst([(capture.JS_EVENT_BUTTON | capture.JS_EVENT_INIT,
                           3, 1)])
        self.assertEqual({}, got)

    def test_the_last_word_on_an_axis_wins(self):
        got = self.burst([(capture.JS_EVENT_AXIS, 2, 9000),
                          (capture.JS_EVENT_AXIS, 2, -9000)])
        self.assertEqual({2: -9000}, got)

    def test_a_trace_starts_knowing_where_the_axes_are(self):
        # `drain`, which every other flow calls at this point, throws
        # that away -- and then a lever parked at one end opens the
        # trace with a move nobody made.
        read_fd, write_fd = os.pipe()
        os.write(write_fd, struct.pack(
            '<IhBB', 0, 9000, capture.JS_EVENT_AXIS | capture.JS_EVENT_INIT, 2))
        os.close(write_fd)
        try:
            events, rest = capture.start_trace(read_fd)
        finally:
            os.close(read_fd)
        self.assertEqual([], events)
        self.assertEqual({2: 9000}, rest)


class TheWatchScreenItself(unittest.TestCase):
    """One frame of it, driven with a pipe and a key that leaves."""

    def one_frame(self):
        read_fd, write_fd = os.pipe()
        os.close(write_fd)                  # nothing to read, ever
        scr = fake.Screen(18, 90, keys=[27])
        t = tui.Tui(scr, tui.Theme(False))
        try:
            got = capture.watch(t, fake.devices()[0], read_fd)
        finally:
            os.close(read_fd)
        return got, scr.text()

    def test_escape_leaves_without_writing_anything(self):
        got, _said = self.one_frame()
        self.assertFalse(got)

    def test_the_findings_box_is_on_the_screen_from_the_first_frame(self):
        # Pinned, so it is in the same place every frame rather than
        # walking down the screen as events arrive.
        _got, said = self.one_frame()
        self.assertIn('moved together', said)

    def test_and_so_is_what_to_do(self):
        _got, said = self.one_frame()
        self.assertIn('Touch one control at a time.', said)


class MakingAndUnmakingADesk(unittest.TestCase):
    """The three that touch the disk: new, rename, delete."""

    class Says:
        """A tui with every answer decided in advance."""

        def __init__(self, typed='', yes=True):
            self.typed, self.yes, self.shown = typed, yes, []

        def ask(self, title, lines=(), default=''):
            return self.typed if self.typed is not None else None

        def confirm(self, title, lines, aside=(), default=True):
            return self.yes

        def popup(self, title, lines, full=False):
            self.shown.append(title)

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.was = devicemap.PROFILES
        devicemap.PROFILES = self.dir

    def tearDown(self):
        devicemap.PROFILES = self.was
        shutil.rmtree(self.dir, ignore_errors=True)

    def files(self):
        return sorted(os.listdir(self.dir))

    def test_a_new_desk_reaches_the_disk(self):
        got = capture._new_desk(self.Says('Fotel'))
        assert got is not None
        self.assertEqual('Fotel', got.name)
        self.assertEqual(['fotel.toml'], self.files())
        self.assertEqual('Fotel', devicemap.load_profiles()[0].name)

    def test_a_desk_with_no_name_is_not_made(self):
        self.assertIsNone(capture._new_desk(self.Says('')))
        self.assertEqual([], self.files())

    def test_a_name_already_taken_does_not_overwrite(self):
        capture._new_desk(self.Says('Fotel'))
        before = open(os.path.join(self.dir, 'fotel.toml')).read()
        tui = self.Says('Fotel')
        self.assertIsNone(capture._new_desk(tui))
        self.assertTrue(tui.shown)
        self.assertEqual(before,
                         open(os.path.join(self.dir, 'fotel.toml')).read())

    def test_renaming_keeps_the_file_it_is_in(self):
        prof = capture._new_desk(self.Says('Fotel'))
        assert prof is not None
        self.assertTrue(capture._rename_desk(self.Says('Kanapa'), prof))
        self.assertEqual(['fotel.toml'], self.files())
        self.assertEqual('Kanapa', devicemap.load_profiles()[0].name)

    def test_renaming_to_the_same_thing_is_not_a_change(self):
        prof = capture._new_desk(self.Says('Fotel'))
        assert prof is not None
        self.assertFalse(capture._rename_desk(self.Says('Fotel'), prof))

    def test_deleting_takes_the_file_with_it(self):
        prof = capture._new_desk(self.Says('Fotel'))
        assert prof is not None
        self.assertTrue(capture._delete_desk(self.Says(yes=True), prof, None))
        self.assertEqual([], self.files())

    def test_saying_no_keeps_it(self):
        prof = capture._new_desk(self.Says('Fotel'))
        assert prof is not None
        self.assertFalse(capture._delete_desk(self.Says(yes=False), prof,
                                              None))
        self.assertEqual(['fotel.toml'], self.files())

    def test_deleting_is_never_the_suggested_answer(self):
        # RETURN on that dialog must not be the one that cannot be undone.
        seen = {}

        class Watches(self.Says):
            def confirm(self, title, lines, aside=(), default=True):
                seen['default'] = default
                return False

        prof = capture._new_desk(self.Says('Fotel'))
        assert prof is not None
        capture._delete_desk(Watches(), prof, None)
        self.assertFalse(seen['default'])
