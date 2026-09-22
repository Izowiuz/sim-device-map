"""The questions, as an order rather than as control flow.

What this replaces is a 215-line function of nested `if kind ==`, with a
second copy of the same menus for editing. So the things worth testing are
the ones that function got wrong by construction: which questions a given
shape actually reaches, what happens when you go back and change your mind,
and whether editing is really the same path as capturing.

The descriptor is checked at load. A question whose `only` names nothing
would never fire and a question whose `uses` names nothing would offer an
empty list -- both silent, and a silent question is one you find out about
by noticing the wizard never asked you something.
"""

import unittest

import questions as q


def sheet():
    return q.read()


def walk(run, answers, settle=False):
    """Answer a run from a dict keyed by question id. Returns the ids asked.

    Bounded, because a rule falsified by its own answer makes the walk ask
    the same question for ever -- and a test that hangs is a test nobody
    reads the output of.
    """
    asked = []
    while (ask := run.next()):
        if ask.id not in answers:
            raise AssertionError(f'nothing to answer {ask.id!r} with')
        if len(asked) > 3 * len(run.sheet.asks):
            raise AssertionError(f'{ask.id!r} keeps being asked: {asked[-6:]}')
        asked.append(ask.id)
        (run.revise if settle else run.answer)(ask, answers[ask.id])
    return asked


HAT4 = {'buttons': ([8, 11, 10, 9, 3], set()), 'kind': 'hat4', 'click': 3,
        'order': [8, 11, 10, 9], 'name': 'Top thumb hat'}
TRIGGER = {'buttons': ([2, 3, 4, 1], set()), 'kind': 'trigger',
           'pull': {'stages': [2, 3, 4], 'rest': 1},
           'returns': 'yes', 'name': 'Main trigger'}
HAT2 = {'buttons': ([10, 12, 9], set()), 'kind': 'hat2',
        'which_way': 'fwd_aft', 'click': 9,
        'order': [10, 12], 'name': 'Thumb rocker'}
BUTTON = {'buttons': ([6], set()), 'kind': 'button',
          'name': 'Pinky button'}


class TheDescriptorItself(unittest.TestCase):
    def test_it_loads(self):
        self.assertTrue(sheet().asks)

    def test_every_rule_it_names_exists(self):
        for a in sheet().asks:
            with self.subTest(ask=a.id):
                self.assertIn(a.only, q.ONLY)

    def test_every_vocabulary_it_names_exists(self):
        s = sheet()
        for a in s.asks:
            if a.uses:
                with self.subTest(ask=a.id):
                    self.assertTrue(s.choices(a))

    def test_a_rule_that_does_not_exist_is_caught_at_load(self):
        s = sheet()
        s.asks[0].only = 'whenever_it_feels_like_it'
        with self.assertRaises(ValueError):
            q.check(s)

    def test_a_vocabulary_that_does_not_exist_is_caught_at_load(self):
        s = sheet()
        s.asks[0].uses = 'shapes_of_things_to_come'
        with self.assertRaises(ValueError):
            q.check(s)

    def test_two_questions_with_one_name_are_caught(self):
        s = sheet()
        s.asks[1].id = s.asks[0].id
        with self.assertRaises(ValueError):
            q.check(s)

    def test_the_three_kinds_of_question_are_all_used(self):
        s = sheet()
        for what in (q.CONTROL, q.DEVICE, q.ALL):
            with self.subTest(of=what):
                self.assertTrue(s.of(what))


class WhichQuestionsAShapeReaches(unittest.TestCase):
    """The whole point of branching: a plain button is two questions, and a
    two-way hat is five, and neither has to be written out twice."""

    def test_a_plain_button_is_asked_almost_nothing(self):
        self.assertEqual(['buttons', 'kind', 'name'],
                         walk(q.Run(sheet()), BUTTON))

    def test_a_hat_is_asked_about_its_click_and_its_order(self):
        self.assertEqual(['buttons', 'kind', 'click', 'order', 'name'],
                         walk(q.Run(sheet()), HAT4))

    def test_a_two_way_hat_has_to_say_which_two_ways(self):
        # Four-way and eight-way hats know their own directions. A rocker
        # could be up/down, left/right or forward/back, and nothing about
        # the shape says which.
        self.assertEqual(['buttons', 'kind', 'which_way', 'click', 'order',
                          'name'], walk(q.Run(sheet()), HAT2))

    def test_a_trigger_is_watched_rather_than_pressed(self):
        self.assertEqual(['buttons', 'kind', 'pull', 'returns', 'name'],
                         walk(q.Run(sheet()), TRIGGER))

    def test_a_trigger_with_no_rest_contact_is_not_asked_about_one(self):
        said = dict(TRIGGER, pull={'stages': [2, 3], 'rest': None})
        self.assertNotIn('returns', walk(q.Run(sheet()), said))

    def test_a_button_is_never_asked_to_click(self):
        # It is the click. Asking is how you get a control that owns its own
        # button twice.
        self.assertNotIn('click', walk(q.Run(sheet()), BUTTON))


class WordsThatReachTheScreen(unittest.TestCase):
    """`HOME`, `EXTENDED` and `BASE` are what the file calls the postures.
    On screen they have to read in a sentence -- "Reach: thumb, in the
    normal grip" -- because that is where they are used."""

    def levels(self):
        return q.read().vocabulary['level']

    def test_a_posture_never_shows_its_storage_name(self):
        for c in self.levels():
            with self.subTest(level=c['name']):
                self.assertNotIn(c['name'], c['says'])

    def test_a_posture_reads_after_a_comma(self):
        for c in self.levels():
            with self.subTest(level=c['name']):
                self.assertTrue(c['says'][:1].islower(), c['says'])
                self.assertFalse(c['says'].endswith('.'), c['says'])

    def test_every_posture_explains_itself(self):
        for c in self.levels():
            with self.subTest(level=c['name']):
                self.assertTrue(c.get('hint'))


class WhatCountsAsAnAnswer(unittest.TestCase):
    """RETURN with nothing pressed used to count, and what it said was
    that the control has no buttons."""

    def ask(self, how='collect', skip=False):
        return q.Ask(id='x', of='control', how=how, says='?', skip=skip)

    def test_nothing_pressed_is_not_an_answer(self):
        self.assertFalse(q.answered(self.ask(), ([], set())))

    def test_something_pressed_is(self):
        self.assertTrue(q.answered(self.ask(), ([4], set())))

    def test_where_nothing_is_the_answer_it_counts(self):
        # A control that does not click has to be able to say so.
        self.assertTrue(q.answered(self.ask('press', skip=True), None))

    def test_otherwise_nothing_is_not(self):
        self.assertFalse(q.answered(self.ask('press'), None))

    def test_the_question_that_collects_is_not_the_skippable_one(self):
        sheet = sheet_of()
        collect = [a for a in sheet.of(q.CONTROL) if a.how == 'collect']
        self.assertTrue(collect)
        for a in collect:
            with self.subTest(ask=a.id):
                self.assertFalse(a.skip)


def sheet_of():
    return q.read()


class NoQuestionUndoesItself(unittest.TestCase):
    """A rule that reads "we have not been told yet" is falsified by being
    told, and `settle` then throws the answer away again.

    It happened: `two_ways_unnamed` was `kind == 'hat2' and not dirs`, and
    answering it supplied the dirs. Nothing noticed, because the walk used
    `answer` and only `revise` settles -- so the wizard lost the answer and
    nothing that ran before it did.
    """

    def both_ways(self, answers):
        """The answers a walk keeps, settling after each one and not."""
        plain, settled = q.Run(sheet()), q.Run(sheet())
        walk(plain, answers)
        walk(settled, answers, settle=True)
        return plain.order, settled.order

    def test_settling_after_every_answer_loses_none_of_them(self):
        for name, said in (('hat4', HAT4), ('trigger', TRIGGER),
                           ('hat2', HAT2), ('button', BUTTON)):
            with self.subTest(shape=name):
                plain, settled = self.both_ways(said)
                self.assertEqual(plain, settled)

    def test_every_answer_leaves_its_own_question_applicable(self):
        for name, said in (('hat4', HAT4), ('trigger', TRIGGER),
                           ('hat2', HAT2), ('button', BUTTON)):
            run = q.Run(sheet())
            while (ask := run.next()):
                run.answer(ask, said[ask.id])
                with self.subTest(shape=name, ask=ask.id):
                    self.assertIn(ask.id, [a.id for a in run.wanted()])


class ChangingYourMind(unittest.TestCase):
    """Going back is the half the old flow had no answer for at all: it
    started over."""

    def run_through(self, answers):
        run = q.Run(sheet())
        walk(run, answers)
        return run

    def test_what_no_longer_applies_is_dropped(self):
        run = self.run_through(HAT4)
        gone = run.revise(run.by_id['kind'], 'button')
        self.assertIn('click', gone)
        self.assertIn('order', gone)

    def test_what_still_applies_is_kept(self):
        # The name you gave a control does not stop being its name because
        # you corrected its shape.
        run = self.run_through(HAT4)
        run.revise(run.by_id['kind'], 'button')
        self.assertEqual('Top thumb hat', run.given['name'])

    def test_a_shape_that_changes_nothing_drops_nothing(self):
        run = self.run_through(HAT4)
        self.assertEqual([], run.revise(run.by_id['kind'], 'hat8'))

    def test_it_says_how_many_went(self):
        # The screen has to be able to tell you, rather than quietly
        # emptying three boxes while you were looking at the question.
        run = self.run_through(HAT2)
        self.assertEqual(3, len(run.revise(run.by_id['kind'], 'button')))

    def test_dropping_reopens_the_questions(self):
        run = self.run_through(BUTTON)
        run.revise(run.by_id['kind'], 'hat4')
        self.assertFalse(run.done)
        ask = run.next()
        assert ask is not None
        self.assertEqual('click', ask.id)


class WhereAnAnswerIsKept(unittest.TestCase):
    """By the question that gave it, never by the field it sets."""

    def test_three_questions_set_states_and_none_clobbers_another(self):
        s = sheet()
        setters = [a.id for a in s.of(q.CONTROL) if a.sets == 'states']
        self.assertGreater(len(setters), 1, setters)
        run = q.Run(s)
        walk(run, HAT2)
        # `order` set states last; `which_way` set dirs. Both survive.
        self.assertEqual([10, 12], run.given['order'])
        self.assertEqual('fwd_aft', run.given['which_way'])

    def test_a_predicate_reads_the_question_not_the_field(self):
        # `pull` and `order` both set `states`, and only one of them
        # produces something with a rest contact in it.
        run = q.Run(sheet())
        walk(run, HAT4)
        self.assertNotIn('returns', run.order)


class WhatTheBoxesShow(unittest.TestCase):
    def test_a_choice_shows_its_words_and_not_its_name(self):
        run = q.Run(sheet())
        walk(run, HAT4)
        said = dict((ask.id, shown) for ask, shown in run.trail())
        self.assertEqual('four-way hat', said['kind'])

    def test_the_trail_is_in_the_order_answered(self):
        run = q.Run(sheet())
        asked = walk(run, HAT2)
        self.assertEqual(asked, [ask.id for ask, _ in run.trail()])

    def test_an_answer_with_no_vocabulary_shows_itself(self):
        run = q.Run(sheet())
        walk(run, BUTTON)
        said = dict((ask.id, shown) for ask, shown in run.trail())
        self.assertEqual('Pinky button', said['name'])

    def test_nothing_shows_as_something(self):
        self.assertEqual('--', q._shown(None))
        self.assertEqual('--', q._shown([]))


class EditingIsTheSamePath(unittest.TestCase):
    """A run that starts with answers in it. The old flow had a second,
    parallel implementation of the same menus for this."""

    def test_a_finished_control_asks_nothing(self):
        run = q.Run(sheet(), given=HAT4)
        self.assertTrue(run.done)
        self.assertEqual(0, run.left())

    def test_a_half_finished_one_picks_up_where_it_stopped(self):
        run = q.Run(sheet(), given={'buttons': ([1], set()),
                                    'kind': 'hat4', 'click': 3})
        ask = run.next()
        assert ask is not None
        self.assertEqual('order', ask.id)

    def test_it_counts_what_is_left(self):
        # click, order, name
        run = q.Run(sheet(), given={'buttons': ([1], set()),
                                    'kind': 'hat4'})
        self.assertEqual(3, run.left())

    def test_answers_to_questions_this_shape_never_asks_are_ignored(self):
        # A control captured as a hat and since changed to a button still
        # has the hat's answers in the file.
        run = q.Run(sheet(), given=dict(BUTTON, click=3, order=[1, 2]))
        self.assertTrue(run.done)
        self.assertEqual(['buttons', 'kind', 'name'],
                         [ask.id for ask, _ in run.trail()])


if __name__ == '__main__':
    unittest.main()
