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

import os
import unittest
from unittest import mock

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


class TheQuestionIsTheHeader(unittest.TestCase):
    """The five ergonomic facts used to be headed by a label -- `found
    without looking` -- with the question a line inside the panel beside
    it, and answers (`high`, `low`, `none`) that did not answer it. You
    read the header, then hunted for what you were being asked."""

    def asks(self):
        return q.read().of(q.ALL)

    def test_every_one_of_them_is_asked_as_a_question(self):
        for a in self.asks():
            with self.subTest(ask=a.id):
                self.assertTrue(a.says.endswith('?'), a.says)

    def test_it_asks_about_one_control_not_about_the_list(self):
        # "Which ones can you hold down?" is asked of the set, and the
        # screen it heads is answered one control at a time.
        for a in self.asks():
            with self.subTest(ask=a.id):
                self.assertNotIn('Which ones', a.says)

    def test_every_answer_it_offers_is_an_answer_to_it(self):
        sheet = q.read()
        for a in self.asks():
            for c in sheet.choices(a):
                with self.subTest(ask=a.id, answer=c['says']):
                    self.assertIn(c['says'], ('yes', 'somewhat', 'no'))


#: Every descriptor has to describe the postures, because their ORDER is
#: the tier. A sheet written for one small rule still carries them.
LEVELS_TOML = ''.join(
    f'[[vocabulary.level]]\nname = "{n}"\nsays = "somewhere"\n'
    for n in ('HOME', 'EXTENDED', 'BASE', 'OFF'))


class TheDescriptorMayNotOfferWhatTheReaderRefuses(unittest.TestCase):
    """The words for a shape live in the descriptor and the closed list of
    them lives in the reader. A shape offered on screen that the reader
    will not accept is a capture you cannot save."""

    def sheet(self, voc, name):
        return ('[[ask]]\nid = "x"\nof = "control"\nhow = "pick"\n'
                f'says = "?"\nsets = "kind"\nuses = "{voc}"\n'
                f'[[vocabulary.{voc}]]\nname = "{name}"\nsays = "a thing"\n'
                + LEVELS_TOML)

    def read(self, text):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.toml',
                                         delete=False) as fh:
            path = fh.name
            fh.write(text)
        try:
            return q.read(path)
        finally:
            os.unlink(path)

    def test_a_shape_the_reader_never_heard_of(self):
        with self.assertRaises(ValueError) as caught:
            self.read(self.sheet('kind', 'wobbler'))
        self.assertIn('wobbler', str(caught.exception))

    def test_an_axis_kind_it_never_heard_of(self):
        with self.assertRaises(ValueError):
            self.read(self.sheet('axis_kind', 'flapper'))

    def test_and_the_real_descriptor_agrees_with_the_reader(self):
        sheet = q.read()
        import devicemap
        self.assertTrue({c['name'] for c in sheet.vocabulary['kind']}
                        <= set(devicemap.SHAPES))
        self.assertTrue({c['name'] for c in sheet.vocabulary['axis_kind']}
                        <= set(devicemap.AXIS_KINDS))


class AScaleIsStoredAsItsNumber(unittest.TestCase):
    """A vocabulary either names things or grades them. A graded one
    carries `value`, and that number is what reaches the file: `low` and
    `high` only sort while two places agree which way round they go."""

    def sheet(self, entry):
        return {'ask': [{'id': 'x', 'of': 'all', 'how': 'pick',
                         'says': 'Well?', 'sets': 'x', 'uses': 'v'}],
                'vocabulary': {'v': [entry],
                               'level': [{'name': n, 'says': 'somewhere'}
                                         for n in ('HOME', 'EXTENDED',
                                                   'BASE', 'OFF')]}}

    def read(self, entry):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.toml',
                                         delete=False) as fh:
            path = fh.name
            fh.write(_toml(self.sheet(entry)))
        try:
            return q.read(path)
        finally:
            os.unlink(path)

    def test_a_number_is_what_gets_stored(self):
        self.assertEqual(3, q.stored({'value': 3, 'says': 'yes'}))

    def test_a_name_is_what_gets_stored_where_there_is_no_number(self):
        self.assertEqual('hat4', q.stored({'name': 'hat4', 'says': 'hat'}))

    def test_a_scale_written_as_a_word_is_refused(self):
        with self.assertRaises(ValueError):
            self.read({'value': 'high', 'says': 'yes'})

    def test_an_entry_that_is_both_is_refused(self):
        with self.assertRaises(ValueError):
            self.read({'name': 'high', 'value': 2, 'says': 'yes'})

    def test_an_entry_that_is_neither_is_refused(self):
        with self.assertRaises(ValueError):
            self.read({'says': 'yes'})


def _toml(data):
    """Just enough TOML to write the one-question sheets above."""
    out = []
    for a in data['ask']:
        out.append('[[ask]]')
        out += [f'{k} = "{v}"' for k, v in a.items()]
    for name, entries in data['vocabulary'].items():
        for c in entries:
            out.append(f'[[vocabulary.{name}]]')
            out += [f'{k} = ' + (f'"{v}"' if isinstance(v, str) else str(v))
                    for k, v in c.items()]
    return '\n'.join(out) + '\n'


class ThePosturesAreOneTable(unittest.TestCase):
    """Their ORDER is the tier -- `LEVELS.index` is how far a control is --
    and their words are what a screen prints. Those lived in two tables
    and had already come apart: the reader knew four postures, the
    descriptor three, and `OFF` was written by the tool with no word for
    it anywhere."""

    def test_the_two_tables_are_the_same_list_in_the_same_order(self):
        import devicemap
        said = tuple(c['name'] for c in q.read().vocabulary['level'])
        self.assertEqual(devicemap.LEVELS, said)

    def test_a_missing_posture_is_refused(self):
        import devicemap
        with mock.patch.object(devicemap, 'LEVELS',
                               ('HOME', 'EXTENDED', 'BASE', 'OFF', 'MOON')):
            with self.assertRaises(ValueError) as caught:
                q.read()
        self.assertIn('MOON', str(caught.exception))

    def test_a_different_order_is_refused(self):
        # Not a set: swapping two of them keeps every word and changes
        # how far away half the controls are.
        import devicemap
        with mock.patch.object(devicemap, 'LEVELS',
                               ('EXTENDED', 'HOME', 'BASE', 'OFF')):
            with self.assertRaises(ValueError):
                q.read()

    def test_every_posture_has_words_for_a_screen(self):
        for c in q.read().vocabulary['level']:
            with self.subTest(level=c['name']):
                self.assertTrue(c.get('says'))
                self.assertTrue(c.get('hint'))

    def test_but_not_every_posture_is_a_round_you_walk(self):
        # There is no round to walk with your hand off the device --
        # offering one asks you to press what you cannot touch.
        sheet = q.read()
        self.assertEqual(['HOME', 'EXTENDED', 'BASE'],
                         [c['name'] for c in q.walkable(sheet)])
        self.assertIn('OFF', [c['name'] for c in sheet.vocabulary['level']])


class EveryWidgetAndFieldTheDescriptorNames(unittest.TestCase):
    """`how` and `sets` were the two words in the descriptor nothing
    checked. A wrong `how` reached `ask_one`, which raises -- in the
    middle of a capture, with curses up. A wrong `sets` on a question
    asked of every control was found on the NEXT load, by which time you
    had answered thirty controls into a field nothing reads."""

    def sheet(self, **ask):
        said = {'id': 'x', 'of': 'all', 'how': 'tick', 'says': 'Well?',
                'sets': 'hold_ok'}
        said.update(ask)
        out = ['[[ask]]'] + [f'{k} = "{v}"' for k, v in said.items()]
        return '\n'.join(out) + '\n' + LEVELS_TOML

    def read(self, text):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.toml',
                                         delete=False) as fh:
            path = fh.name
            fh.write(text)
        try:
            return q.read(path)
        finally:
            os.unlink(path)

    def test_a_widget_nothing_draws(self):
        with self.assertRaises(ValueError) as caught:
            self.read(self.sheet(how='pik'))
        self.assertIn('pik', str(caught.exception))

    def test_and_it_says_which_ones_there_are(self):
        with self.assertRaises(ValueError) as caught:
            self.read(self.sheet(how='pik'))
        self.assertIn('collect', str(caught.exception))

    def test_a_field_no_control_has(self):
        with self.assertRaises(ValueError) as caught:
            self.read(self.sheet(sets='hold_okay'))
        self.assertIn('hold_okay', str(caught.exception))

    def test_a_control_question_files_its_answer_where_it_likes(self):
        # `sets` on a control question is the name an answer is filed
        # under while the walk runs -- `buttons`, `push`, `silent_at` --
        # and `build_group` folds those into the file. Only a question
        # asked of every control writes the field directly.
        self.read(self.sheet(of='control', how='press', sets='push'))

    def test_every_widget_declared_is_one_the_descriptor_uses(self):
        # Otherwise the list grows words nothing draws, which is how it
        # came to be worth checking in the first place.
        used = {a.how for a in q.read().asks}
        self.assertEqual(set(q.WIDGETS), used)

    def test_and_every_fact_asked_of_all_is_a_field_of_a_control(self):
        import dataclasses, devicemap
        fields = {f.name for f in dataclasses.fields(devicemap.Group)}
        for a in q.read().of(q.ALL):
            with self.subTest(ask=a.id):
                self.assertIn(a.sets, fields)


class AVocabularyEntryMayNotSayWhatNothingReads(unittest.TestCase):
    """`[[ask]]` is a dataclass and refuses `notee` outright. A vocabulary
    entry is a plain dict, so it took `hnit` and dropped the hint off
    every screen that shows that choice."""

    def sheet(self, entry):
        out = ['[[ask]]', 'id = "x"', 'of = "control"', 'how = "pick"',
               'says = "?"', 'sets = "kind"', 'uses = "v"',
               '[[vocabulary.v]]']
        for k, v in entry.items():
            out.append(f'{k} = ' + (f'"{v}"' if isinstance(v, str)
                                    else str(v).lower()))
        return '\n'.join(out) + '\n' + LEVELS_TOML

    def read(self, entry):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.toml',
                                         delete=False) as fh:
            path = fh.name
            fh.write(self.sheet(entry))
        try:
            return q.read(path)
        finally:
            os.unlink(path)

    def test_a_misspelt_key_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self.read({'name': 'button', 'says': 'a button', 'hnit': 'x'})
        self.assertIn('hnit', str(caught.exception))

    def test_and_it_says_which_keys_there_are(self):
        with self.assertRaises(ValueError) as caught:
            self.read({'name': 'button', 'says': 'a button', 'hnit': 'x'})
        self.assertIn('hint', str(caught.exception))

    def test_an_entry_with_no_words_is_refused(self):
        # Every entry reaches a screen. One with nothing to print is a
        # blank row you cannot tell from the one above it.
        with self.assertRaises(ValueError):
            self.read({'name': 'button'})

    def test_a_good_entry_loads(self):
        self.read({'name': 'button', 'says': 'a button'})

    def test_the_real_descriptor_says_nothing_odd(self):
        for name, entries in q.read().vocabulary.items():
            for c in entries:
                with self.subTest(vocabulary=name):
                    self.assertFalse(set(c) - set(q.ENTRY_KEYS))
