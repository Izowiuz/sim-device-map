"""From a control to its answers and back.

`_already` reads a captured control as the answers that would have produced
it; `build_group` turns answers back into a control. Between them they are
what makes editing the same walk as capturing, and a control that does not
survive the trip is a control the wizard quietly rewrites.

The real captures are the fixtures, because they are the shapes that exist.
"""

import os
import unittest

import capture
import devicemap
import questions as q


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
        for dev in devicemap.load_all():
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

    def test_the_comment_block_at_the_top_is_kept(self):
        for prof in devicemap.load_profiles():
            _back, text = self.rewritten(prof)
            with self.subTest(rig=prof.name):
                self.assertTrue(text.lstrip().startswith('#'), text[:40])

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
        return devicemap.load_all()[0]

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
    def test_a_guess_says_so(self):
        said = capture._spot_said({'part': 'panel', 'level': 'OFF',
                                   'how': 'guessed'})
        self.assertIn('guessed', said)

    def test_the_ordinary_case_is_not_worth_a_column(self):
        # `how` earns its place only when it is not what you would assume.
        said = capture._spot_said({'part': 'stick', 'level': 'HOME',
                                   'finger': 'thumb', 'how': 'measured'})
        self.assertNotIn('how', said)
        self.assertIn('thumb', said)

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
        dev = devicemap.load_all()[0]
        for level in devicemap.GRIPPED:
            with self.subTest(level=level):
                self.assertEqual(dev.kind, capture._part_of(dev, level))

    def test_off_the_grip_it_is_on_the_base(self):
        dev = devicemap.load_all()[0]
        self.assertEqual(f'{dev.kind}_base', capture._part_of(dev, 'BASE'))

    def test_every_part_it_names_is_in_the_vocabulary(self):
        for dev in devicemap.load_all():
            for level in devicemap.LEVELS[:3]:
                with self.subTest(dev=dev.slug, level=level):
                    self.assertIn(capture._part_of(dev, level),
                                  devicemap.PARTS)


class RecordingAFact(unittest.TestCase):
    def test_it_reaches_the_file_and_the_thing_in_hand(self):
        # Both, because the screen redraws from the parsed control and the
        # writer emits from the raw one. Setting only the first loses it on
        # save; only the second and the list still says "to go".
        dev = devicemap.load_all()[0]
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
        real = devicemap.load_all()[0]
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
        real = devicemap.load_all()[0]
        self.dev = devicemap.Device(copy.deepcopy(real._raw), real.path)
        self.dev.under(devicemap.profile())
        self.g = next(x for x in self.dev.groups(bindable=True) if x.id)
        self.sheet = capture.SHEET

    def ask(self, sets):
        return next(a for a in self.sheet.of(q.ALL) if a.sets == sets)

    def test_a_yes_or_no_flips(self):
        ask = self.ask('hold_ok')
        was = self.g.fact('hold_ok')
        capture._step(self.dev, self.g, ask, self.sheet.choices(ask))
        self.assertEqual(not was, self.g.fact('hold_ok'))

    def test_flipping_twice_puts_it_back(self):
        # Pressing the thing again is how you undo a press you did not mean.
        ask = self.ask('hold_ok')
        was = self.g.fact('hold_ok')
        capture._step(self.dev, self.g, ask, self.sheet.choices(ask))
        capture._step(self.dev, self.g, ask, self.sheet.choices(ask))
        self.assertEqual(was, self.g.fact('hold_ok'))

    def test_answering_makes_it_answered(self):
        ask = self.ask('hold_ok')
        self.assertEqual('guessed', self.g.told('hold_ok'))
        capture._step(self.dev, self.g, ask, self.sheet.choices(ask))
        self.assertEqual('measured', self.g.told('hold_ok'))

    def test_three_steps_walk_round(self):
        ask = self.ask('blind_distinct')
        picks = self.sheet.choices(ask)
        seen = []
        for _ in range(len(picks) + 1):
            capture._step(self.dev, self.g, ask, picks)
            seen.append(self.g.fact('blind_distinct'))
        self.assertEqual(len(picks), len(set(seen)))
        self.assertEqual(seen[0], seen[-1])

    def test_it_only_ever_lands_on_a_real_choice(self):
        ask = self.ask('accident_risk')
        picks = [c['name'] for c in self.sheet.choices(ask)]
        for _ in range(7):
            capture._step(self.dev, self.g, ask, self.sheet.choices(ask))
            self.assertIn(self.g.fact('accident_risk'), picks)


class WhatNoRoundReached(unittest.TestCase):
    """Whatever none of the rounds reached is something you take a hand
    off the device for -- but only once every round has been walked."""

    def test_a_control_nobody_reached_ends_up_off(self):
        dev = devicemap.load_all()[0]
        said = {'access': {}}
        capture._rest_are_off(dev, said)
        every = [g.id for g in dev.groups(bindable=True) if g.id]
        self.assertEqual(sorted(every), sorted(said['access']))
        self.assertTrue(all(sp[0]['level'] == 'OFF'
                            for sp in said['access'].values()))

    def test_one_that_was_reached_is_left_alone(self):
        dev = devicemap.load_all()[0]
        one = next(g for g in dev.groups(bindable=True) if g.id)
        mine = [{'part': 'throttle', 'level': 'HOME', 'finger': 'thumb'}]
        said = {'access': {one.id: list(mine)}}
        capture._rest_are_off(dev, said)
        self.assertEqual(mine, said['access'][one.id])

    def test_nothing_that_cannot_be_bound_is_placed(self):
        dev = devicemap.load_all()[0]
        said = {'access': {}}
        capture._rest_are_off(dev, said)
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
