"""What the wizard's screens say, read back as strings.

The screens are two things: what they say, which is here, and the curses
calls that put it on a terminal, which are not. Only the first has anything
to get wrong.

The trail of boxes is most of this file. It is the part of the wizard that
was not there at all before -- the old flow could not go back, it could only
start over -- and a trail that silently stops at four boxes has lost three.
"""

import re
import unittest

import capture
import devicemap
import fake
import questions as q
import screens
import tui
import tui as ui


def run_through(**answers):
    """A finished run over one control."""
    sheet = q.read()
    run = q.Run(sheet)
    while (ask := run.next()):
        run.answer(ask, answers[ask.id])
    return run


HAT2 = dict(buttons=([10, 12, 9], set()), kind='hat2', which_way='fwd_aft',
            click=9, order=[10, 12], name='Thumb rocker')
BUTTON = dict(buttons=([6], set()), kind='button', name='Pinky')


class TheTrailOfAnswers(unittest.TestCase):
    """A row of boxes was the first shape this took and it was the wrong
    one: an answer is a name and a value, which reads down a column."""

    def trail(self, answers, width=56):
        return screens.trail_tree(run_through(**answers).trail(), width)

    def test_nothing_answered_draws_nothing(self):
        self.assertEqual([], screens.trail_tree([], 56))

    def test_every_answer_is_there(self):
        got = '\n'.join(t for _tone, t in self.trail(HAT2))
        for shown in ('two-way hat', 'Thumb rocker', 'forward and back'):
            with self.subTest(shown=shown):
                self.assertIn(shown[:20], got)

    def test_the_last_one_closes_the_tree(self):
        got = [t for _tone, t in self.trail(HAT2)]
        self.assertIn(tui.LAST, got[-1])
        self.assertEqual(1, sum(1 for t in got if tui.LAST in t))

    def test_the_names_line_up(self):
        # A column, or it is a list of sentences with glyphs in front.
        said = [t for _tone, t in self.trail(HAT2)
                if tui.BRANCH in t or tui.LAST in t]
        hits = [re.match(r'\s*[\u251c\u2514] .+?\s\s+(\S)', t) for t in said]
        self.assertTrue(all(hits), said)
        self.assertEqual(1, len({m.start(1) for m in hits if m}), said)

    def test_a_long_answer_is_cut_and_not_wrapped(self):
        # A tree that wraps stops being a tree: the second half of a line
        # lands under the glyph instead of beside it.
        got = self.trail(HAT2, 40)
        self.assertTrue(all(len(t) <= 40 for _tone, t in got), got)

    def test_without_a_heading_it_hangs_off_nothing(self):
        # A branch indented under a line that is not there is a branch off
        # the frame.
        said = screens.trail_tree(run_through(**BUTTON).trail(), 56, lead='')
        self.assertTrue(all(t.startswith((tui.BRANCH, tui.LAST))
                            for _tone, t in said), said)

    def test_with_a_heading_it_hangs_under_it(self):
        said = [t for _tone, t in self.trail(BUTTON)]
        self.assertIn('answered so far', said)
        branches = [t for t in said if tui.BRANCH in t or tui.LAST in t]
        self.assertTrue(all(t.startswith('  ') for t in branches), branches)

    def test_it_says_what_it_is(self):
        got = [t for _tone, t in self.trail(BUTTON)]
        self.assertIn('answered so far', got)

    def test_the_names_are_the_captions(self):
        got = '\n'.join(t for _tone, t in self.trail(BUTTON))
        self.assertIn('button IDs', got)


class HowFarAControlHasGot(unittest.TestCase):
    """The list is the progress indicator, so the three states it can show
    are the only thing it is really for."""

    def dev(self, access=True, label='Top hat', **facts):
        g = fake.group('hat4', [1, 2, 3, 4], label=label, id='top-hat',
                       **facts)
        dev = fake.device(groups=[g], slug='rig-a')
        said = {'top-hat': [{'level': 'HOME',
                             'finger': 'thumb'}]} if access else {}
        prof = devicemap.Profile(
            {'device': [{'slug': 'rig-a', 'hand': 'right', 'access': said}]},
            '<fake>')
        return dev.under(prof)

    def rows(self, **kw):
        return screens.control_rows(self.dev(**kw))

    def test_nobody_has_placed_it(self):
        row = self.rows(access=False)[0]
        self.assertEqual('unset', row.tone)
        self.assertIn('no reach', row.text)

    def test_placed_but_standing_on_its_shape(self):
        row = self.rows()[0]
        self.assertEqual('guessed', row.tone)
        self.assertIn('5 facts', row.text)

    def test_answered_for(self):
        row = self.rows(hold_ok=True, rapid_ok=True, modifier_ok=False,
                        blind_distinct=2, accident_risk=0)[0]
        self.assertEqual('measured', row.tone)
        self.assertNotIn('to go', row.text)

    def test_one_answer_short_is_not_finished(self):
        row = self.rows(hold_ok=True, rapid_ok=True, modifier_ok=False,
                        blind_distinct=2)[0]
        self.assertEqual('guessed', row.tone)

    def test_a_control_with_no_name_does_not_borrow_its_kind(self):
        # `button` where a name should be is indistinguishable from a
        # control somebody called `button`, and the row reads as finished.
        dev = fake.device(groups=[fake.group('button', [5], label='',
                                             id='button-5')])
        row = screens.control_rows(dev.under(None))[0]
        self.assertIn('js 5', row.text)
        self.assertIn('a name', row.text)
        self.assertEqual('unset', row.tone)

    def test_a_button_nobody_described_gets_a_row_of_its_own(self):
        # As one pile it was a single row, and that row did nothing: the
        # natural gesture -- cursor on what is missing, RETURN -- was the
        # one that was dead.
        dev = fake.device(groups=[fake.bucket([6, 7, 8],
                                             label='Not yet captured')])
        rows = screens.control_rows(dev.under(None))
        self.assertEqual([6, 7, 8], [r.button for r in rows])
        for row in rows:
            with self.subTest(row=row.text):
                self.assertIn(screens.NOT_A_CONTROL['uncaptured'][0],
                              row.text)
                self.assertNotIn('position', row.text)
                self.assertNotIn('tier', row.text)

    def test_a_loose_button_says_which_one_it_is(self):
        dev = fake.device(groups=[fake.bucket([19])])
        row = screens.control_rows(dev.under(None))[0]
        self.assertIn('js 19', row.text)
        self.assertEqual(19, row.button)
        self.assertIsNone(row.group)

    def test_placed_but_unnamed_is_still_unfinished(self):
        # Reach is not the only thing a control needs. One you measured and
        # never named reads as done if the name is not checked for.
        row = self.rows(label='')[0]
        self.assertEqual('unset', row.tone)
        self.assertIn('a name', row.text)

    def test_a_row_does_not_say_the_same_thing_twice(self):
        dev = fake.device(groups=[fake.group('button', [5], label='Pinky',
                                             id='pinky')])
        row = screens.control_rows(dev.under(None))[0]
        self.assertEqual(1, row.text.count('reach'), row.text)

    def test_each_state_has_its_own_mark(self):
        self.assertEqual(3, len(set(screens.MARK.values())))
        self.assertEqual(set(screens.MARK), set(screens.TONE))

    def test_a_row_that_is_not_a_control_says_which_it_is(self):
        for status in screens.NOT_A_CONTROL:
            if status == 'uncaptured':
                continue            # a row each, not one row: see above
            dev = fake.device(groups=[fake.group('', [1, 2], label='',
                                                 id=status, status=status)])
            row = screens.control_rows(dev.under(None))[0]
            with self.subTest(status=status):
                self.assertIn(screens.NOT_A_CONTROL[status][0], row.text)
                self.assertIn('js 1, 2', row.text)
                # Not a control, so neither of the columns that are about
                # controls: it has no positions and nothing reaches it.
                self.assertIn('2 buttons', row.text)
                self.assertNotIn('position', row.text)
                self.assertNotIn('tier', row.text)
                self.assertNotIn('reach', row.text)

    def test_a_control_with_nothing_behind_it_is_asked_nothing(self):
        dev = fake.device(groups=[fake.unwired([1, 2],
                                             label='Nothing', id='none')])
        row = screens.control_rows(dev.under(None))[0]
        self.assertEqual('unset', row.tone)
        self.assertNotIn('to go', row.text)


class TheRealRig(unittest.TestCase):
    def test_every_control_gets_a_row(self):
        for dev in fake.devices():
            rows = screens.control_rows(dev)
            with self.subTest(dev=dev.slug):
                self.assertEqual(len(dev.groups()), len(rows))

    def test_the_devices_say_what_is_outstanding(self):
        have = fake.devices()
        prof = fake.rig(*have)
        rows = screens.device_rows(prof, fake.devices(prof))
        self.assertTrue(rows)
        for _tone, text, dev in rows:
            with self.subTest(dev=dev.slug):
                self.assertIn(dev.role, text)

    def test_the_rig_on_file_is_listed(self):
        rows = screens.profile_rows(devicemap.load_profiles())
        self.assertTrue(rows)
        self.assertIn('device', rows[0][1])


class ANoteUnderAQuestion(unittest.TestCase):
    """A note in the descriptor is wrapped wherever the TOML happened to
    end a line. Honouring those breaks folds it twice -- at the file's
    width and again at the box's -- and it comes out shredded."""

    def test_a_paragraph_comes_back_as_one_line(self):
        ask = q.Ask(id='x', of='control', how='pick', says='?',
                    note='one two three\nfour five six')
        self.assertEqual(['one two three four five six'],
                         screens.note_lines(ask))

    def test_a_blank_line_is_where_a_paragraph_ends(self):
        ask = q.Ask(id='x', of='control', how='pick', says='?',
                    note='first one\nhere\n\nsecond one')
        self.assertEqual(['first one here', 'second one'],
                         screens.note_lines(ask))

    def test_no_note_is_no_lines(self):
        ask = q.Ask(id='x', of='control', how='pick', says='?')
        self.assertEqual([], screens.note_lines(ask))

    def test_the_shipped_notes_carry_no_stray_breaks(self):
        # Every one of them is written across several lines in the file.
        for ask in q.read().asks:
            for line in screens.note_lines(ask):
                with self.subTest(ask=ask.id):
                    self.assertNotIn('\n', line)

    def test_two_paragraphs_do_not_run_together(self):
        got = tui.aside_of(['first', 'second'])
        said = [t for _tone, t in got]
        self.assertEqual('', said[said.index('first') + 1])


class WhatABoxIsLabelled(unittest.TestCase):
    def test_the_descriptor_can_name_it(self):
        sheet = q.read()
        said = next(a for a in sheet.of(q.CONTROL) if a.id == 'buttons')
        self.assertEqual('button IDs', screens.caption(said))

    def test_otherwise_the_id_reads_as_words(self):
        sheet = q.read()
        said = next(a for a in sheet.of(q.CONTROL) if a.id == 'which_way')
        self.assertEqual('which way', screens.caption(said))

    def test_no_label_is_left_looking_like_a_field_name(self):
        for a in q.read().asks:
            with self.subTest(ask=a.id):
                self.assertNotIn('_', screens.caption(a))


class TheFiveFacts(unittest.TestCase):
    """Per question, not per control: each of these covers every control
    at once, because a comparison made on separate screens does not line
    up with the next one."""

    def setUp(self):
        self.sheet = q.read()
        self.dev = fake.unanswered()
        self.asks = self.sheet.of(q.ALL)

    def test_one_row_per_question(self):
        self.assertEqual(len(self.asks),
                         len(screens.fact_rows(self.dev, self.asks)))

    def test_there_are_fewer_rows_than_controls_times_questions(self):
        self.assertLess(len(self.asks),
                        len(self.dev.groups(bindable=True)) * len(self.asks))

    def test_a_row_says_how_many_are_still_to_answer(self):
        rows = screens.fact_rows(self.dev, self.asks)
        left = screens._left_to_answer(self.dev, self.asks[0])
        self.assertIn(str(left), rows[0][1])

    def test_the_counts_line_up(self):
        # A column, or it is five sentences of different lengths.
        rows = screens.fact_rows(self.dev, self.asks)
        hits = [re.match(r'\S .+?\s\s+(\S)', t) for _tone, t in rows]
        self.assertTrue(all(hits), rows)
        self.assertEqual(1, len({m.start(1) for m in hits if m}), rows)

    def test_a_row_reads_as_words_and_not_as_a_field(self):
        for tone, text in screens.fact_rows(self.dev, self.asks):
            with self.subTest(text=text):
                self.assertNotIn('_', text)

    def test_answered_for_reads_differently(self):
        dev = fake.device(groups=[fake.group(
            'button', [1], label='Pinky', id='pinky', hold_ok=True,
            rapid_ok=True, modifier_ok=True, blind_distinct=2,
            accident_risk=0)])
        rows = screens.fact_rows(dev.under(None), self.asks)
        self.assertTrue(all(t == screens.TONE['measured']
                            for t, _x in rows), rows)

    def test_the_side_says_the_question_and_how_many_are_left(self):
        # The count, not the wording: a test that pins the prose breaks
        # every time the prose gets better, which is most of the time.
        head, said = screens.fact_side(self.dev, self.asks, 0)
        shown = '\n'.join(t for _tone, t in said)
        left = screens._left_to_answer(self.dev, self.asks[0])
        self.assertEqual(screens.caption(self.asks[0]), head)
        self.assertIn(self.asks[0].says, shown)
        self.assertIn(str(left), shown)

    def test_the_side_says_so_when_nothing_is_left(self):
        dev = fake.device(groups=[fake.group(
            'button', [1], label='Pinky', id='pinky', hold_ok=True,
            rapid_ok=True, modifier_ok=True, blind_distinct=2,
            accident_risk=0)])
        _head, said = screens.fact_side(dev.under(None), self.asks, 0)
        shown = [t for tone, t in said if tone == screens.TONE['measured']]
        self.assertTrue(shown, said)
        with_left = screens.fact_side(self.dev, self.asks, 0)[1]
        self.assertNotEqual([t for tone, t in with_left
                             if tone == screens.TONE['measured']], shown)


class AnsweringOneFact(unittest.TestCase):
    def setUp(self):
        self.sheet = q.read()
        self.dev = fake.unanswered()
        self.ctrls = [g for g in self.dev.groups(bindable=True) if g.id]

    def ask(self, sets):
        return next(a for a in self.sheet.of(q.ALL) if a.sets == sets)

    def picks(self, ask):
        return self.sheet.choices(ask)

    def test_one_row_per_control(self):
        ask = self.ask('hold_ok')
        rows = screens.answer_rows(self.dev, ask, self.ctrls, self.picks(ask))
        self.assertEqual(len(self.ctrls), len(rows))

    def test_a_yes_and_a_no_do_not_read_alike(self):
        self.assertNotEqual(screens.SAID[True], screens.SAID[False])

    def test_a_row_says_the_answer_and_what_it_is_about_and_no_more(self):
        # How far away the control is used to ride along here. It is true
        # and beside the point: the question is about the feel of the
        # thing under your finger, and it was a column to read past on
        # every row of twenty-six.
        for ask in self.sheet.of(q.ALL):
            picks = self.picks(ask)
            said = {q.stored(c): c['says'] for c in picks}
            rows = screens.answer_rows(self.dev, ask, self.ctrls, picks)
            for g, (_tone, text) in zip(self.ctrls, rows):
                got = g.fact(ask.sets)
                mark = ('' if got is None
                        else screens.SAID[got] if isinstance(got, bool)
                        else said[got])
                with self.subTest(ctrl=g.id, ask=ask.id):
                    self.assertEqual(
                        mark, text.replace(g.label or g.kind, '').strip())

    def test_a_row_shows_a_mark_and_not_python(self):
        ask = self.ask('hold_ok')
        one = self.ctrls[0]
        one.hold_ok = True
        try:
            rows = screens.answer_rows(self.dev, ask, self.ctrls,
                                       self.picks(ask))
        finally:
            one.hold_ok = None
        shown = '\n'.join(t for _tone, t in rows)
        self.assertNotIn('True', shown)
        self.assertNotIn('False', shown)
        self.assertIn(screens.SAID[True], shown)

    def test_a_control_nobody_answered_for_is_left_blank(self):
        # Blank, not a no: those are different, and a mark for one of
        # them standing in for the other is the whole reason the table of
        # what a shape usually is had to go.
        ask = self.ask('hold_ok')
        rows = screens.answer_rows(self.dev, ask, self.ctrls, self.picks(ask))
        for g, (_tone, text) in zip(self.ctrls, rows):
            if g.told('hold_ok') == 'missing':
                with self.subTest(ctrl=g.id):
                    self.assertNotIn(screens.SAID[True], text)
                    self.assertNotIn(screens.SAID[False], text)

    def test_a_graded_row_reads_as_the_word_and_not_as_the_number(self):
        # The file stores 0, 1 or 2 so that anything ordering these
        # compares numbers. A row showing `2` would make you learn the
        # table the vocabulary already holds.
        ask = self.ask('blind_distinct')
        picks = self.picks(ask)
        one = self.ctrls[0]
        for c in picks:
            one.blind_distinct = q.stored(c)
            try:
                (_tone, text), *_ = screens.answer_rows(self.dev, ask,
                                                        self.ctrls, picks)
            finally:
                one.blind_distinct = None
            with self.subTest(answer=c['says']):
                self.assertTrue(text.startswith(c['says']), text)
                self.assertNotIn(str(q.stored(c)), text)

    def test_the_controls_line_up_under_a_graded_answer(self):
        # The words are not the same length, so the column is as wide as
        # the widest of them or the names walk right across the panel.
        ask = self.ask('blind_distinct')
        picks = self.picks(ask)
        was = [g.fact(ask.sets) for g in self.ctrls]
        for g, c in zip(self.ctrls, picks * len(self.ctrls)):
            setattr(g, ask.sets, q.stored(c))
        try:
            rows = screens.answer_rows(self.dev, ask, self.ctrls, picks)
        finally:
            for g, got in zip(self.ctrls, was):
                setattr(g, ask.sets, got)
        at = {text.index(g.label or g.kind)
              for g, (_tone, text) in zip(self.ctrls, rows)}
        self.assertEqual(1, len(at), [t for _tone, t in rows])

    def test_an_answer_reads_as_a_word_and_not_as_python(self):
        ask = self.ask('hold_ok')
        _head, said = screens.answer_side(self.dev, ask, self.ctrls, 0,
                                          self.picks(ask))
        shown = '\n'.join(t for _tone, t in said)
        self.assertNotIn('True', shown)
        self.assertNotIn('False', shown)
        self.assertRegex(shown, r'\b(yes|no)\b')

    def test_every_note_reaches_the_panel_whole(self):
        for ask in self.sheet.of(q.ALL):
            _head, said = screens.answer_side(self.dev, ask, self.ctrls, 0,
                                              self.picks(ask))
            shown = [t for _tone, t in said]
            for para in screens.note_lines(ask):
                with self.subTest(ask=ask.id):
                    self.assertIn(para, shown)

    def test_it_carries_the_answer_and_the_sentences_and_no_more(self):
        # How many positions it has and how far away it is are true and
        # beside the point: the question is about the feel of the thing.
        ask = self.ask('hold_ok')
        _head, said = screens.answer_side(self.dev, ask, self.ctrls, 0,
                                          self.picks(ask))
        shown = [t for _tone, t in said if t]
        want = screens.note_lines(ask)
        self.assertEqual(len(want) + 1, len(shown), shown)
        self.assertNotIn('tier', ' '.join(shown))
        self.assertNotIn('position', ' '.join(shown))

    def test_no_answer_says_so_rather_than_showing_one(self):
        ask = self.ask('hold_ok')
        self.assertEqual('missing', self.ctrls[0].told(ask.sets))
        _head, said = screens.answer_side(self.dev, ask, self.ctrls, 0,
                                          self.picks(ask))
        (_tone, first), *_ = said
        self.assertIn('no answer', first)

    def test_the_question_is_not_repeated_beside_its_own_frame(self):
        # The question is the title of the panel this one sits beside.
        # Printed twice on one screen it reads as two questions until you
        # have compared them.
        for ask in self.sheet.of(q.ALL):
            head, said = screens.answer_side(self.dev, ask, self.ctrls, 0,
                                             self.picks(ask))
            shown = [t for _tone, t in said]
            with self.subTest(ask=ask.id):
                self.assertEqual(self.ctrls[0].label, head)
                self.assertNotIn(ask.says, shown)

    def test_it_does_not_repeat_what_the_border_says(self):
        # The keys are in the sill. Saying them again costs two rows of
        # the note, which is the half that tells you how to answer.
        ask = self.ask('hold_ok')
        _head, said = screens.answer_side(self.dev, ask, self.ctrls, 0,
                                          self.picks(ask))
        shown = '\n'.join(t for _tone, t in said)
        self.assertNotIn('SPACE', shown)
        self.assertNotIn('Press it', shown)


class EveryRowFitsThePanelItIsIn(unittest.TestCase):
    """`browse` cuts a row at the panel edge without a word about it.

    The lid does the same with a title, and that one was caught by
    reading the screen. A row is cut mid-word instead -- "26 with no
    answe" -- which reads as something broken rather than something
    shortened, and the tail is where these rows say how much is left.
    """

    def setUp(self):
        self.sheet = q.read()
        self.dev = fake.devices()[0]
        scr = fake.Screen(16, 80)
        t = ui.Tui(scr, ui.Theme(False))
        (_ly, lx, _lh, lw), _right = t.halves(*scr.getmaxyx())
        self.room = ui.text_in(lx, lw)[1]
        self.width = lw

    def fits(self, rows):
        for _tone, text in rows:
            with self.subTest(row=text):
                self.assertLessEqual(len(text), self.room)

    def fits_the_box(self, body):
        _y, x, _h, bw = ui.box_for(body, 24, 80, self.dev.product, True)
        room = ui.text_in(x, bw)[1]
        for text in body:
            with self.subTest(row=text):
                self.assertLessEqual(len(text), room)

    def test_a_device_with_nothing_described_yet(self):
        # Loose buttons and loose axes are the widest rows there are:
        # every column is blank and the reason sits at the end of them.
        fresh = fake.device(kind='stick',
                            groups=[fake.bucket([0, 1])],
                            axes=[{'index': 0}, {'index': 11}])
        rows = screens.control_rows(fresh)
        # Two loose buttons, and a control for each of the two axes.
        self.assertEqual(4, len(rows))
        self.fits_the_box([r.text for r in rows])

    def test_every_control_on_the_main_list(self):
        # A full-width box rather than a panel, so its own width, and it
        # is the row with the most columns on it.
        rows = screens.control_rows(self.dev)
        body = [r.text for r in rows]
        _y, x, _h, bw = ui.box_for(body, 24, 80, self.dev.product, True)
        room = ui.text_in(x, bw)[1]
        for text in body:
            with self.subTest(row=text):
                self.assertLessEqual(len(text), room)

    def test_the_five_facts(self):
        self.fits(screens.fact_rows(self.dev, self.sheet.of(q.ALL)))

    def test_every_control_under_one_fact(self):
        # With the longest answer against every one of them: the column
        # is as wide as the widest word in the vocabulary, and a row is
        # only at its widest once something has been answered.
        controls = [g for g in self.dev.groups(bindable=True) if g.id]
        for ask in self.sheet.of(q.ALL):
            picks = self.sheet.choices(ask)
            was = [g.fact(ask.sets) for g in controls]
            if picks:
                widest = max(picks, key=lambda c: len(c['says']))
                for g in controls:
                    setattr(g, ask.sets, q.stored(widest))
            try:
                self.fits(screens.answer_rows(self.dev, ask, controls, picks))
            finally:
                for g, got in zip(controls, was):
                    setattr(g, ask.sets, got)

    def test_a_stage_is_headed_by_its_question_and_keeps_its_count(self):
        # `lid` drops what will not fit, silently. A question long enough
        # to push the counter off the border loses the one thing that
        # says how much of the list is left.
        controls = [g for g in self.dev.groups(bindable=True) if g.id]
        for ask in self.sheet.of(q.ALL):
            count = f'{len(controls)}/{len(controls)}'
            border = ui.lid(self.width, ask.says, count)
            with self.subTest(ask=ask.id):
                self.assertIn(ask.says, border)
                self.assertIn(count, border)

    def test_the_fingers_and_their_grips(self):
        self.fits(screens.reach_rows(screens.reach_rounds(
            self.dev, fake.rig(self.dev), self.sheet.vocabulary['level'])))


class ThePickerAtTheDoor(unittest.TestCase):
    """Which device, and how far each has got.

    It used to count buttons the file had heard of, which on both of
    these is every button there is -- so it said 51/51 described about a
    device with not one answer given.
    """

    class Plugged:
        def __init__(self, dev, ok=True, status='exact'):
            self.device, self.ok, self.status = dev, ok, status

        def explain(self):
            return 'nothing in the map looks like this'

    def setUp(self):
        self.found = [self.Plugged(d) for d in fake.devices()]

    def test_it_counts_what_is_answered_and_not_what_is_wired(self):
        for m, (_tone, text) in zip(self.found,
                                    screens.found_rows(self.found)):
            done, total = screens.described(m.device)
            with self.subTest(dev=m.device.slug):
                self.assertFalse(m.device.unknown())
                self.assertIn(f'{done}/{total}', text)
                self.assertNotIn(f'{m.device.n_buttons}/'
                                 f'{m.device.n_buttons}', text)

    def test_a_device_nobody_has_touched_counts_its_buttons(self):
        # Controls are made by pressing buttons, so a fresh device has
        # none of them -- and a ratio of them is 0 of 0, which reads as
        # finished. Buttons come from the firmware and are there at once.
        fresh = fake.device(groups=[fake.bucket([0, 1, 2, 3])])
        (tone, text), = screens.found_rows([self.Plugged(fresh)])
        self.assertIn('4 buttons', text)
        self.assertNotIn('0/0', text)
        self.assertNotEqual(screens.TONE['measured'], tone)

    def test_and_says_so_in_the_hint_as_well(self):
        fresh = fake.device(groups=[fake.bucket([0, 1, 2, 3])])
        said = ' '.join(screens.found_hints(self.Plugged(fresh)))
        self.assertIn('4 buttons', said)

    def test_a_device_with_no_buttons_at_all_is_not_called_finished(self):
        # Nothing to sort and nothing to answer, which is not the same
        # as done: it is a device the map knows nothing about.
        (tone, text), = screens.found_rows(
            [self.Plugged(fake.device(groups=[]))])
        self.assertNotEqual(screens.TONE['measured'], tone)
        self.assertTrue(text.strip())

    def test_a_fresh_device_is_not_called_finished(self):
        # It has no controls, so there is nothing to be outstanding
        # about -- which is the same trap the ratio fell into.
        fresh = fake.device(groups=[fake.bucket([0, 1, 2, 3])])
        said = ' '.join(screens.found_hints(self.Plugged(fresh))).lower()
        self.assertNotIn('nothing outstanding', said)

    def test_a_device_with_nothing_left_says_so(self):
        done = fake.device(groups=[fake.group(
            'button', [0], label='One', id='one', hold_ok=True,
            rapid_ok=True, modifier_ok=True, blind_distinct=2,
            accident_risk=0)])
        done.under(devicemap.Profile({'name': 'x', 'device': [{
            'slug': done.slug, 'hand': 'left',
            'access': {'one': [{'level': 'HOME',
                                'finger': 'thumb'}]}}]}, '<test>'))
        said = ' '.join(screens.found_hints(self.Plugged(done))).lower()
        self.assertIn('nothing outstanding', said)

    def test_buttons_first_and_answers_after(self):
        # One job at a time: sorting the buttons into controls comes
        # before anything can be asked about a control.
        half = fake.device(groups=[fake.bucket([0]),
                                   fake.group('button', [1], label='One',
                                              id='one')])
        (_tone, text), = screens.found_rows([self.Plugged(half)])
        self.assertIn('1 button', text)
        self.assertNotIn('controls', text)

    def test_a_device_with_nothing_answered_does_not_look_finished(self):
        for m, (tone, _text) in zip(self.found,
                                    screens.found_rows(self.found)):
            done, _total = screens.described(m.device)
            if not done:
                with self.subTest(dev=m.device.slug):
                    self.assertNotEqual(screens.TONE['measured'], tone)

    def test_a_row_fits_the_dialog(self):
        room = ui.text_in(0, ui.DIALOG)[1]
        for _tone, text in screens.found_rows(self.found):
            with self.subTest(row=text):
                self.assertLessEqual(len(text), room)

    def test_a_device_that_did_not_match_says_why(self):
        odd = self.Plugged(fake.devices()[0], ok=False, status='drift')
        self.assertIn(odd.explain(), screens.found_hints(odd))
        self.assertNotIn(odd.explain(),
                         screens.found_hints(self.found[0]))

    def test_the_hint_says_what_is_outstanding(self):
        said = ' '.join(screens.found_hints(self.found[0]))
        dev = self.found[0].device
        blank = sum(1 for g in dev.groups(bindable=True) if not g.access)
        self.assertIn(str(blank), said)


class WhatARowSaysAControlHas(unittest.TestCase):
    """A dial and a mini-stick report an axis and have no positions."""

    def setUp(self):
        self.dev = fake.devices()[0]

    def test_a_control_with_only_axes_is_not_empty(self):
        for g in self.dev.groups(bindable=True):
            if g.axes and not g.places:
                with self.subTest(ctrl=g.id):
                    said = screens._owns(self.dev, g)
                    self.assertIn('axis' if len(g.axes) == 1 else 'axes',
                                  said)
                    self.assertNotIn('0', said)

    def test_a_control_with_positions_counts_them(self):
        for g in self.dev.groups(bindable=True):
            if g.places:
                with self.subTest(ctrl=g.id):
                    self.assertIn(ui.plural(len(g.places), 'position'),
                                  screens._owns(self.dev, g))

    def test_a_control_with_only_a_click_says_so(self):
        # Otherwise its row says nothing at all about what is on it.
        for g in self.dev.groups(bindable=True):
            if g.push is not None and not g.places:
                with self.subTest(ctrl=g.id):
                    self.assertIn('click', screens._owns(self.dev, g))

    def test_a_pile_of_buttons_is_counted_in_buttons(self):
        for g in self.dev.groups():
            if not g.bindable and g.all_buttons:
                with self.subTest(kind=g.kind):
                    self.assertIn('button', screens._owns(self.dev, g))
                    self.assertNotIn('position', screens._owns(self.dev, g))


class AnUnsweptAxisIsNotFinished(unittest.TestCase):
    """How far an axis travels and how much it wanders are measurements,
    not opinions you supply -- and the list called a lever finished on
    the strength of the five ergonomic answers it had, while nobody had
    ever moved it."""

    def setUp(self):
        dev = fake.unanswered(on_a_desk=False)
        prof = devicemap.Profile({'name': 'x', 'device': [
            {'slug': dev.slug, 'hand': 'left',
             'access': {g.id: [{'level': 'HOME', 'finger': 'thumb'}]
                        for g in dev.groups(bindable=True) if g.id}}]}, '<x>')
        self.dev = dev.under(prof)
        self.one = next(g for g in self.dev.groups(bindable=True) if g.axes)
        # Every control answered, so the only thing outstanding anywhere
        # is the axis -- otherwise the device row is `guessed` for
        # reasons that have nothing to do with sweeping.
        for g in self.dev.groups(bindable=True):
            for f in screens.FACTS:
                setattr(g, f, True)

    def swept(self, yes):
        a = self.dev.axis(self.one.axes[0])
        assert a is not None
        a.stepped, a.range, a.noise = ((False, 65534, 2) if yes
                                       else (None, None, None))

    def test_a_control_whose_axis_nobody_moved_is_not_done(self):
        self.swept(False)
        self.assertEqual('guessed', screens._state(self.dev, self.one))
        self.assertIn('1 axis', screens._left_said(self.dev, self.one))

    def test_and_once_it_is_measured_it_is(self):
        self.swept(True)
        self.assertEqual('measured', screens._state(self.dev, self.one))
        self.assertEqual('', screens._left_said(self.dev, self.one))

    def test_half_a_measurement_is_not_one(self):
        # A sweep with no settle leaves the noise unmeasured, and a
        # control with an axis nobody let settle is not described.
        a = self.dev.axis(self.one.axes[0])
        assert a is not None
        a.stepped, a.range, a.noise = False, 65534, None
        self.assertEqual('guessed', screens._state(self.dev, self.one))

    def test_the_device_row_counts_it_too(self):
        self.swept(True)
        (tone, text, _d), = screens.device_rows(None, [self.dev])
        self.assertEqual('measured', tone)
        self.assertIn('nothing outstanding', text)
        self.swept(False)
        (tone, text, _d), = screens.device_rows(None, [self.dev])
        self.assertEqual('guessed', tone)
        self.assertIn('to go', text)

    def test_and_a_control_with_no_axes_is_unaffected(self):
        self.swept(False)
        plain = next(g for g in self.dev.groups(bindable=True)
                     if not g.axes)
        for f in screens.FACTS:
            setattr(plain, f, True)
        self.assertEqual('measured', screens._state(self.dev, plain))


class TheReachRounds(unittest.TestCase):
    """Fifteen rounds for a whole device, not fifteen per control -- and
    a list of them rather than fifteen screens in a row, because a row of
    steps says neither how far in you are nor which are worth doing."""

    def setUp(self):
        self.sheet = q.read()
        self.dev = fake.devices()[0]
        self.prof = fake.rig(self.dev)
        self.rounds = screens.reach_rounds(self.dev, self.prof,
                                           self.sheet.vocabulary['level'])

    def walked(self, found=(), done=True):
        """One posture's worth of rounds, the thumb's holding `found`."""
        lvl = self.sheet.vocabulary['level'][0]
        return [screens.Round(lvl, 'thumb', list(found), done)]

    def test_one_round_per_posture_and_finger(self):
        want = len(self.sheet.vocabulary['level']) * len(devicemap.FINGERS)
        self.assertEqual(want, len(self.rounds))

    def test_there_are_fewer_rounds_than_controls(self):
        # The whole point: asking per control would ask the same question
        # twenty-six times and get answers that do not compare.
        self.assertLess(len(self.rounds),
                        len(self.dev.groups(bindable=True)))

    def test_a_round_that_found_something_says_how_much(self):
        rounds = self.walked(['a', 'b'])
        said = '\n'.join(t for _tone, t in screens.reach_rows(rounds))
        self.assertIn('thumb', said)
        self.assertIn(ui.plural(2, 'control'), said)

    def test_a_round_nobody_has_walked_says_so(self):
        said = '\n'.join(t for _tone, t in
                         screens.reach_rows(self.walked(done=False)))
        self.assertIn('not done yet', said)

    def test_a_round_that_reached_nothing_is_not_one_left_to_do(self):
        # Both list no controls, so the words are the whole difference.
        (_tone, a), = [r for r in screens.reach_rows(self.walked(done=True))
                       if r[0] != 'subhead']
        (_tone, b), = [r for r in screens.reach_rows(self.walked(done=False))
                       if r[0] != 'subhead']
        self.assertNotEqual(a, b)

    def test_a_posture_heads_its_own_fingers(self):
        rows = screens.reach_rows(self.rounds)
        heads = [t for tone, t in rows if tone == 'subhead']
        self.assertEqual([c['says'].lower()
                          for c in self.sheet.vocabulary['level']],
                         [t.lower() for t in heads])

    def test_a_heading_starts_like_a_sentence(self):
        # The same words read mid-sentence on the other half of the
        # screen ("thumb, in the normal grip"); as a heading they start.
        for tone, t in screens.reach_rows(self.rounds):
            if tone == 'subhead':
                with self.subTest(head=t):
                    self.assertEqual(t[:1], t[:1].upper())

    def test_a_row_does_not_mark_what_its_own_words_already_say(self):
        for tone, t in screens.reach_rows(self.rounds):
            if tone != 'subhead':
                with self.subTest(row=t):
                    self.assertNotIn(screens.MARK['measured'], t)
                    self.assertNotIn(screens.MARK['guessed'], t)

    def test_return_on_a_heading_goes_to_a_round_worth_doing(self):
        rows = screens.reach_rows(self.rounds)
        heads = [n for n in range(len(rows))
                 if screens._round_at(self.rounds, n) is None]
        for n in heads:
            with self.subTest(row=n):
                to = screens.next_round_at(self.rounds, n)
                one = screens._round_at(self.rounds, to)
                assert one is not None
                mine = [r for r in self.rounds
                        if r.level['name'] == one.level['name']]
                self.assertIn(one, mine)
                if any(not r.done for r in mine):
                    self.assertFalse(one.done)

    def test_a_round_row_stays_where_it_is(self):
        rows = screens.reach_rows(self.rounds)
        for n in range(len(rows)):
            if screens._round_at(self.rounds, n) is not None:
                with self.subTest(row=n):
                    self.assertEqual(n, screens.next_round_at(self.rounds, n))

    def test_a_round_is_done_only_once_somebody_has_walked_it(self):
        # Walked, and nothing else. `access` alone cannot say it: the
        # wizard writes spots for a finger and the walk it came from in
        # the same breath, and a hand-edited file says nothing about who
        # pressed what.
        said = dict(self.prof.entry(self.dev.slug) or {})
        one = next(g for g in self.dev.groups(bindable=True) if g.id)
        lvl = self.sheet.vocabulary['level'][0]
        said['access'] = {one.id: [{
                                    'level': lvl['name'],
                                    'finger': 'thumb'}]}
        rig = devicemap.Profile({'name': 'x', 'device': [said]}, '<test>')
        rounds = screens.reach_rounds(self.dev, rig,
                                      self.sheet.vocabulary['level'])
        got = next(r for r in rounds
                   if r.finger == 'thumb' and r.level is lvl)
        self.assertEqual([one.id], got.found)
        self.assertFalse(got.done)

        said['rounds'] = [{'level': lvl['name'], 'finger': 'thumb'}]
        rig = devicemap.Profile({'name': 'x', 'device': [said]}, '<test>')
        rounds = screens.reach_rounds(self.dev, rig,
                                      self.sheet.vocabulary['level'])
        self.assertTrue(next(r for r in rounds if r.finger == 'thumb'
                             and r.level is lvl).done)

    def test_every_control_it_found_is_listed(self):
        # `and 3 more` is the one thing on this panel you cannot act on.
        lvl = self.sheet.vocabulary['level'][0]
        every = [g.id for g in self.dev.groups(bindable=True) if g.id]
        named = {g.id: g.label or g.kind
                 for g in self.dev.groups(bindable=True)}
        _h, said = screens.reach_side(
            self.dev, [screens.Round(lvl, 'thumb', every, True)], 1, [],
            room=12)
        shown = '\n'.join(t for _tone, t in said)
        self.assertNotIn('more', shown)
        for ctrl in every:
            with self.subTest(ctrl=ctrl):
                self.assertIn(named[ctrl], shown)

    def test_the_explanation_gives_way_before_the_list_does(self):
        lvl = self.sheet.vocabulary['level'][0]
        every = [g.id for g in self.dev.groups(bindable=True) if g.id][:7]
        one = [screens.Round(lvl, 'thumb', every, True)]
        roomy = screens.reach_side(self.dev, one, 1, [], room=99)[1]
        tight = screens.reach_side(self.dev, one, 1, [], room=12)[1]
        self.assertGreater(len(roomy), len(tight))
        hint = (lvl.get('hint') or [''])[0]
        self.assertIn(hint, [t for _tone, t in roomy])
        self.assertNotIn(hint, [t for _tone, t in tight])
        # The posture is cheaper to lose than the hint, so it is the one
        # that survives the first squeeze.
        said = lvl['says']
        self.assertIn(said[:1].upper() + said[1:],
                      [t for _tone, t in tight])

    def test_and_what_it_found_survives_either_way(self):
        # Even past what the panel can hold: it overflows rather than
        # dropping a control, because the list is the answer and a
        # shorter one is a wrong answer.
        lvl = self.sheet.vocabulary['level'][0]
        every = [g.id for g in self.dev.groups(bindable=True) if g.id]
        one = [screens.Round(lvl, 'thumb', every, True)]
        for room in (99, 12, 1):
            with self.subTest(room=room):
                said = screens.reach_side(self.dev, one, 1, [], room=room)[1]
                self.assertEqual(len(every),
                                 sum(1 for _tone, t in said
                                     if t.startswith('  ')))

    def test_nothing_on_screen_calls_it_a_round(self):
        # A word for the thing that appears nowhere else on the screen:
        # the list says grips and fingers, and the screen has to say the
        # same. Twice reported as not understood.
        note = screens.note_lines(self.sheet.of(q.DEVICE)[0])
        said = list(note)
        for n in range(len(screens.reach_rows(self.rounds))):
            head, rows = screens.reach_side(self.dev, self.rounds, n, note)
            said += [head] + [t for _tone, t in rows]
        said += [t for _tone, t in screens.reach_rows(self.rounds)]
        for one in self.rounds:
            title, aside, says = screens.round_prompt(one)
            said += [title, says] + list(aside)
        for t in said:
            with self.subTest(said=t):
                self.assertNotRegex(t.lower(), r'\bround')

    def test_every_panel_title_fits_the_panel(self):
        # `lid` drops what will not fit, so a title too long for the
        # narrowest panel is a title nobody ever reads in full -- and the
        # longest ones, which need reading most, are the ones that go.
        scr = fake.Screen(16, 80)
        t = ui.Tui(scr, ui.Theme(False))
        (_, _, _, _), (_ry, _rx, _rh, rw) = t.halves(*scr.getmaxyx())
        rows = screens.reach_rows(self.rounds)
        for n in range(len(rows)):
            head, _said = screens.reach_side(self.dev, self.rounds, n, [])
            with self.subTest(head=head):
                self.assertIn(head, ui.lid(rw, head))

    def test_the_panel_says_what_it_says_inside_the_panel(self):
        # `browse` truncates the detail panel at its last row without a
        # word about it, so anything past that row is written and never
        # read. The explanation of the whole screen lives there.
        scr = fake.Screen(16, 80)
        t = ui.Tui(scr, ui.Theme(False))
        (_ly, _lx, _lw, _l), (_ry, _rx, rh, rw) = t.halves(*scr.getmaxyx())
        _at, room = ui.text_in(_rx, rw)
        note = screens.note_lines(self.sheet.of(q.DEVICE)[0])
        for n in range(len(screens.reach_rows(self.rounds))):
            _head, said = screens.reach_side(self.dev, self.rounds, n, note)
            wrapped = [f for _tone, t2 in said for f in ui.fit(room, t2)]
            with self.subTest(row=n):
                self.assertLessEqual(len(wrapped), rh - 2)

    def test_a_round_panel_says_which_posture_it_is(self):
        rows = screens.reach_rows(self.rounds)
        n = next(n for n in range(len(rows))
                 if screens._round_at(self.rounds, n) is not None)
        one = screens._round_at(self.rounds, n)
        assert one is not None
        head, said = screens.reach_side(self.dev, self.rounds, n, [])
        self.assertIn(screens.finger_said(one.finger), head)
        shown = ' '.join(t for _tone, t in said).lower()
        self.assertIn(one.level['says'].lower(), shown)

    def test_the_side_names_controls_and_not_their_ids(self):
        one = next(g for g in self.dev.groups(bindable=True)
                   if g.id and g.label)
        _head, said = screens.reach_side(self.dev, self.walked([one.id]),
                                         1, [])
        shown = '\n'.join(t for _tone, t in said)
        self.assertIn(one.label, shown)
        self.assertNotIn(one.id, shown)

    def test_a_posture_row_explains_the_whole_thing(self):
        head, said = screens.reach_side(self.dev, self.rounds, 0,
                                        ['why this exists'])
        self.assertIn('why this exists', [t for _tone, t in said])
        self.assertNotIn('Reached this way:', [t for _tone, t in said])
        self.assertTrue(head)

    def test_the_explanation_is_paragraphs_and_not_one_block(self):
        _head, said = screens.reach_side(self.dev, self.rounds, 0,
                                         ['first para', 'second para'])
        shown = [t for _tone, t in said]
        self.assertIn('', shown[shown.index('first para') + 1:
                                shown.index('second para')])

    def test_a_round_does_not_repeat_the_explanation(self):
        # You read it on the heading row you came past; here it pushes
        # the posture off the screen.
        _head, said = screens.reach_side(self.dev, self.rounds, 1,
                                         ['what the rounds are for'])
        self.assertNotIn('what the rounds are for',
                         [t for _tone, t in said])

    def test_a_posture_says_what_the_hand_is_doing(self):
        for c in self.sheet.vocabulary['level']:
            with self.subTest(level=c['name']):
                said = ' '.join(c.get('hint') or [])
                self.assertIn('hand', said + c['says'])

    def test_a_walked_round_that_found_nothing_is_not_an_unwalked_one(self):
        # Same empty list of controls, two different things: one you did
        # and one you have not got to.
        rounds = screens.reach_rounds(self.dev, self.prof,
                                      self.sheet.vocabulary['level'])
        lvl, finger = rounds[0].level, rounds[0].finger
        done = [screens.Round(lvl, finger, [], True)]
        todo = [screens.Round(lvl, finger, [], False)]
        _h, a = screens.reach_side(self.dev, done, 1, [])
        _h, b = screens.reach_side(self.dev, todo, 1, [])
        self.assertNotEqual([t for _tone, t in a], [t for _tone, t in b])

    def test_a_round_screen_says_how_to_answer_nothing(self):
        # Most rounds reach nothing, and an empty one is an answer. Say
        # so, or the screen looks like one you can only cancel out of.
        rounds = screens.reach_rounds(self.dev, self.prof,
                                      self.sheet.vocabulary['level'])
        _title, aside, says = screens.round_prompt(rounds[0])
        self.assertTrue(any('RETURN' in t for t in aside))
        self.assertIn('RETURN', says)

    def test_a_round_screen_carries_the_posture_and_not_the_preamble(self):
        rounds = screens.reach_rounds(self.dev, self.prof,
                                      self.sheet.vocabulary['level'])
        # A finger round: the whole-hand one drops the posture hint on
        # purpose, because that hint is about a hand that stayed put.
        one = next(r for r in rounds if r.finger != devicemap.HAND)
        title, aside, _says = screens.round_prompt(one)
        self.assertIn(one.level['says'], title)
        for t in one.level.get('hint') or []:
            self.assertIn(t, aside)
        for t in screens.note_lines(self.sheet.of(q.DEVICE)[0]):
            if t:
                self.assertNotIn(t, aside)

    def test_a_finger_is_named_so_it_reads(self):
        # `middle` on its own reads as the middle of something.
        self.assertEqual('middle finger', screens.finger_said('middle'))
        self.assertEqual('thumb', screens.finger_said('thumb'))
        for f in devicemap.FINGERS:
            with self.subTest(finger=f):
                self.assertTrue(screens.finger_said(f))


class WhatWasThatButton(unittest.TestCase):
    """The list says which button a row is. This says which row a button
    is, which is the question you actually have: a piece of plastic under
    your thumb and no idea what it is called."""

    def dev(self):
        return fake.devices()[0]

    def test_it_names_the_control(self):
        dev = self.dev()
        g = next(x for x in dev.groups(bindable=True) if x.label)
        said = [t for _tone, t in screens.what_is(dev, g.buttons[0])]
        self.assertIn(f'js {g.buttons[0]}', said)
        self.assertIn(g.label, said)

    def test_it_says_which_way_a_hat_position_points(self):
        dev = self.dev()
        g = next(x for x in dev.groups(bindable=True) if x.names)
        said = [t for _tone, t in screens.what_is(dev, g.buttons[0])]
        self.assertIn(g.names[0], said)

    def test_a_button_nobody_owns(self):
        dev = self.dev()
        said = [t for _tone, t in screens.what_is(dev, 9999)]
        self.assertIn('js 9999', said)
        self.assertIn(screens.NOT_A_CONTROL['uncaptured'][0], said)

    def test_it_finds_the_row_the_button_is_on(self):
        dev = self.dev()
        rows = screens.control_rows(dev)
        g = next(x for x in dev.groups(bindable=True) if x.label)
        at = screens.row_of(rows, dev, g.buttons[0])
        assert at is not None
        self.assertIs(g, rows[at].group)

    def test_a_loose_button_finds_its_own_row(self):
        dev = fake.device(groups=[fake.bucket([6, 7, 8])])
        rows = screens.control_rows(dev.under(None))
        at = screens.row_of(rows, dev, 7)
        assert at is not None
        self.assertEqual(7, rows[at].button)

    def test_a_button_on_no_row_finds_none(self):
        dev = self.dev()
        self.assertIsNone(screens.row_of(screens.control_rows(dev),
                                         dev, 9999))


class RowsThatAreNotControls(unittest.TestCase):
    def test_each_kind_is_explained_in_the_help(self):
        said = '\n'.join(t for _tone, t in screens.key_help())
        for name, why in screens.NOT_A_CONTROL.values():
            with self.subTest(row=name):
                self.assertIn(name, said)
                self.assertIn(why, said)

    def test_the_why_is_not_on_every_line_of_the_list(self):
        # It belongs in the help. On the list it pushes the row past the
        # width and wraps, and the same sentence thirty times is noise.
        dev = fake.device(groups=[fake.unwired([1, 2], id='u')])
        row = screens.control_rows(dev.under(None))[0]
        for _name, why in screens.NOT_A_CONTROL.values():
            self.assertNotIn(why, row.text)


class TheKeysAndTheHelp(unittest.TestCase):
    """One list, so the border and the help cannot disagree about which
    keys there are. Two lists is one list that goes stale."""

    def test_the_help_names_every_key(self):
        said = '\n'.join(t for _tone, t in screens.key_help())
        for k, _says, what in screens.KEYS:
            with self.subTest(key=k):
                self.assertIn(what, said)

    def test_the_border_offers_every_key_worth_a_reminder(self):
        shown = ' '.join(screens.sill_keys())
        for k, says, _what in screens.KEYS:
            if k == '?':
                continue                        # it lives in the tail
            with self.subTest(key=k):
                self.assertIn(says, shown)

    def test_help_is_not_in_the_border(self):
        # It is in the bottom-right corner instead, where the count is not.
        self.assertNotIn('? help', screens.sill_keys())

    def test_every_key_can_be_pressed(self):
        for k, _says, _what in screens.KEYS:
            if k == '\u21b5':
                continue                        # RETURN is the list's own
            with self.subTest(key=k):
                self.assertIn(k, screens.takes())

    def test_a_letter_answers_in_either_case(self):
        for k, _says, _what in screens.KEYS:
            if k.isalpha():
                with self.subTest(key=k):
                    self.assertIn(k.upper(), screens.takes())

    def test_every_mark_is_explained(self):
        # The rule, not the wording: each mark gets a line of its own, and
        # no two say the same thing. Pinning the prose means the test
        # breaks when the prose improves.
        said = [t for _tone, t in screens.key_help()]
        at = said.index('MARKS')
        rows = [t.strip() for t in said[at + 1:] if t.strip()]
        explained = {}
        for mark in screens.MARK.values():
            shown = mark.strip() or '\u2423'
            hit = [r for r in rows if r.startswith(shown + ' ')]
            with self.subTest(mark=shown):
                self.assertEqual(1, len(hit), rows)
            explained[shown] = hit[0][len(shown):].strip()
        self.assertEqual(len(explained), len(set(explained.values())))

    def test_the_blank_mark_has_something_to_see(self):
        # Nothing to draw reads as a line that forgot its first column.
        said = '\n'.join(t for _tone, t in screens.key_help())
        self.assertIn('\u2423', said)

    def test_it_says_what_each_key_does_and_not_why(self):
        # Man page, not an essay: the reasoning lives in comments.
        for _k, _says, what in screens.KEYS:
            with self.subTest(what=what):
                self.assertLessEqual(len(what), 52)
                self.assertNotIn('because', what)


class SayingWhatWentAway(unittest.TestCase):
    def test_nothing_went(self):
        self.assertEqual('', screens.dropped_said([]))

    def test_one_went(self):
        said = screens.dropped_said(['click'])
        self.assertIn('1 answer', said)
        self.assertIn('click', said)

    def test_several_went(self):
        # The screen has to be able to say this, rather than quietly
        # emptying three boxes while you were looking at the question.
        said = screens.dropped_said(['which_way', 'click', 'order'])
        self.assertIn('3 answers', said)
        self.assertIn('order', said)


if __name__ == '__main__':
    unittest.main()


class TheLiveTrace(unittest.TestCase):
    """Events as they happen, with the map's own names on them."""

    def setUp(self):
        self.dev = fake.devices()[0]
        self.events = [(1.00, 'button', 0, 1), (1.20, 'button', 0, 0),
                       (2.00, 'axis', 0, 12000)]

    def test_one_row_per_event(self):
        self.assertEqual(len(self.events),
                         len(screens.trace_rows(self.dev, self.events)))

    def test_it_says_what_the_map_calls_the_thing(self):
        said = '\n'.join(t for _tone, t in
                         screens.trace_rows(self.dev, self.events))
        self.assertIn(self.dev.button_label(0), said)

    def test_a_press_and_a_release_do_not_read_alike(self):
        rows = screens.trace_rows(self.dev, self.events)
        self.assertNotEqual(rows[0][1], rows[1][1])

    def test_it_says_how_long_since_the_one_before(self):
        # Most of the answer is in the gap: a lever's own switch trips
        # within a moment of the travel, a second press never does.
        said = '\n'.join(t for _tone, t in
                         screens.trace_rows(self.dev, self.events))
        self.assertIn('0.20', said)

    def test_the_first_event_has_nothing_to_be_after(self):
        rows = screens.trace_rows(self.dev, self.events)
        self.assertNotIn('+', rows[-1][1])

    def test_a_long_trace_is_cut_to_what_fits_keeping_the_newest(self):
        many = [(float(n), 'button', 0, 1) for n in range(50)]
        rows = screens.trace_rows(self.dev, many, room=5)
        self.assertEqual(5, len(rows))
        self.assertIn(' 49.00', rows[0][1])

    def test_the_newest_is_at_the_top(self):
        # Where your eye already is, and the rows that fall off the
        # bottom are then the ones you have stopped caring about.
        rows = screens.trace_rows(self.dev, self.events)
        self.assertIn(f'{self.events[-1][0]:6.2f}', rows[0][1])
        self.assertIn(f'{self.events[0][0]:6.2f}', rows[-1][1])

    def test_a_gap_is_still_the_time_since_the_row_below_it(self):
        # The trace is reversed, not the clock.
        rows = screens.trace_rows(self.dev, self.events)
        self.assertIn('0.20', rows[-2][1])

    def test_the_findings_bring_no_heading_of_their_own(self):
        # They go in a box that is already titled.
        moved = capture.what_moved_together(
            [(1.00, 'axis', 0, 12000), (1.10, 'button', 0, 1)])
        for tone, _t in screens.together_rows(self.dev, moved):
            self.assertNotEqual('subhead', tone)

    def test_with_nothing_found_it_says_so_rather_than_nothing(self):
        said = screens.together_rows(self.dev, [])
        self.assertTrue(said)
        self.assertTrue(all(t for _tone, t in said))

    def test_a_finding_names_both_things_in_words(self):
        moved = capture.what_moved_together(
            [(1.00, 'axis', 0, 12000), (1.10, 'button', 0, 1)])
        said = '\n'.join(t for _tone, t in
                         screens.together_rows(self.dev, moved))
        self.assertIn(self.dev.button_label(0), said)
        self.assertIn('axis 0', said.replace(
            screens._thing_said(self.dev, 'axis', 0), 'axis 0'))


class TheDeskList(unittest.TestCase):
    """Which desk this is, and what each one holds."""

    def setUp(self):
        self.have = devicemap.load_all(bare=True)
        self.rigs = [
            devicemap.Profile({'name': 'Biurko', 'device': [
                {'slug': self.have[0].slug, 'role': 'throttle',
                 'hand': 'left'}]}, '<a>'),
            devicemap.Profile({'name': 'Fotel', 'device': []}, '<b>'),
            devicemap.Profile({'name': 'Gdzies', 'device': [
                {'slug': 'nic-takiego'}]}, '<c>')]

    def test_one_row_per_desk(self):
        self.assertEqual(len(self.rigs),
                         len(screens.profile_rows(self.rigs)))

    def test_the_one_you_are_at_says_so_in_words(self):
        # Not only in a tone: with no colours to hand the theme falls
        # back to bold, and "the bold one" is not something you read off
        # a list of two.
        rows = screens.profile_rows(self.rigs, self.rigs[0])
        self.assertNotEqual(rows[0][1].strip(), rows[1][1].strip())
        plain = [t for tone, t in rows if tone != 'measured']
        marked, = [t for tone, t in rows if tone == 'measured']
        self.assertTrue(all(len(t) < len(marked) for t in plain))

    def test_with_no_desk_in_hand_none_is_marked(self):
        for tone, _t in screens.profile_rows(self.rigs):
            self.assertNotEqual('measured', tone)

    def test_a_row_fits_the_panel(self):
        scr = fake.Screen(16, 80)
        t = ui.Tui(scr, ui.Theme(False))
        (_ly, lx, _lh, lw), _r = t.halves(*scr.getmaxyx())
        room = ui.text_in(lx, lw)[1]
        for _tone, text in screens.profile_rows(self.rigs, self.rigs[0]):
            with self.subTest(row=text):
                self.assertLessEqual(len(text), room)

    def test_a_desk_names_its_devices_the_way_the_rest_of_the_tool_does(self):
        _head, said = screens.profile_side(self.rigs, 0, None, self.have)
        shown = '\n'.join(t for _tone, t in said)
        self.assertIn(self.have[0].product, shown)
        self.assertNotIn(self.have[0].slug, shown)

    def test_a_desk_naming_a_capture_nobody_has_says_so(self):
        _head, said = screens.profile_side(self.rigs, 2, None, self.have)
        shown = '\n'.join(t for _tone, t in said)
        self.assertIn('nic-takiego', shown)
        self.assertIn('no capture on file', shown)

    def test_an_empty_desk_says_it_is_empty(self):
        _head, said = screens.profile_side(self.rigs, 1, None, self.have)
        self.assertTrue(any('No devices' in t for _tone, t in said))

    def test_the_desk_you_are_at_is_not_offered_again(self):
        _h, here = screens.profile_side(self.rigs, 0, self.rigs[0], self.have)
        _h, other = screens.profile_side(self.rigs, 0, None, self.have)
        self.assertNotIn('↵ works at this desk.',
                         [t for _tone, t in here])
        self.assertIn('↵ works at this desk.',
                      [t for _tone, t in other])

    def test_the_border_shows_fewer_keys_than_there_are(self):
        # Five do not fit in the 46 columns beside the panel, and `?`
        # is what shows the rest.
        self.assertLess(len(screens.desk_keys()), len(screens.DESK_KEYS) + 1)
        self.assertIn('?', screens.desk_takes())

    def test_every_key_is_explained_exactly_once(self):
        said = '\n'.join(t for _tone, t in screens.desk_help())
        for k, _says, what, _sill in screens.DESK_KEYS:
            with self.subTest(key=k):
                self.assertEqual(1, said.count(what))

    def test_the_key_that_sets_a_hand_is_on_the_border(self):
        # It was behind `?`, and the only way to say which hand is on
        # what went unfound -- with the two words it sets printed in the
        # panel beside it the whole time.
        self.assertIn('e hands', screens.desk_keys())

    def test_the_border_says_no_more_than_it_has_room_for(self):
        scr = fake.Screen(24, 80)
        t = ui.Tui(scr, ui.Theme(False))
        (_y, _x, _h, lw), _right = t.halves(24, 80)
        self.assertLessEqual(len(ui.SEP.join(screens.desk_keys())), lw - 4)

    def test_and_every_key_off_it_is_still_reachable(self):
        takes = screens.desk_takes()
        for k, _says, _what, sill in screens.DESK_KEYS:
            if k.isalpha() and not sill:
                with self.subTest(key=k):
                    self.assertIn(k, takes)


class WhatADeskSaysAboutOneDevice(unittest.TestCase):
    """Which hand is on it, which nothing else asks."""

    def setUp(self):
        self.have = devicemap.load_all(bare=True)
        self.prof = devicemap.Profile({'name': 'x', 'device': [
            {'slug': self.have[0].slug, 'role': 'throttle', 'hand': 'left'},
            {'slug': self.have[1].slug}]}, '<x>')

    def test_a_device_with_no_hand_said_is_not_finished(self):
        rows = screens.rig_rows(self.prof, self.have)
        self.assertEqual(screens.TONE['measured'], rows[0][0])
        self.assertNotEqual(screens.TONE['measured'], rows[1][0])

    def test_and_says_so_in_words(self):
        rows = screens.rig_rows(self.prof, self.have)
        self.assertIn('left hand', rows[0][1])
        self.assertIn('no hand said', rows[1][1])

    def test_the_panel_says_why_the_hand_matters(self):
        _head, said = screens.rig_side(self.prof, self.have, 1)
        shown = ' '.join(t for _tone, t in said)
        self.assertIn('at once', shown)

    def test_it_says_whether_letting_go_stops_you_flying(self):
        _h, a = screens.rig_side(self.prof, self.have, 0)
        self.prof.devices[0]['leaving_home_releases_flight'] = True
        _h, b = screens.rig_side(self.prof, self.have, 0)
        self.assertNotEqual([t for _tone, t in a], [t for _tone, t in b])


class WhatASaveWouldChange(unittest.TestCase):
    """Per control, because that is the unit you worked in: a diff of the
    text would say `states = [` moved, which is true and says nothing
    about what you did."""

    def raw(self, *groups, axes=(), fingerprint=None):
        return {'group': list(groups), 'axis': list(axes),
                'fingerprint': fingerprint or {}}

    def ctrl(self, ident, label, **kw):
        return dict({'id': ident, 'kind': 'button', 'label': label,
                     'states': [{'button': 1}]}, **kw)

    def test_nothing_moved_is_no_rows_at_all(self):
        one = self.raw(self.ctrl('a', 'Thumb'))
        self.assertEqual([], screens.save_rows(one, dict(one)))

    def test_a_control_that_was_not_there_says_new(self):
        got = screens.save_rows(self.raw(),
                                self.raw(self.ctrl('a', 'Thumb')))
        self.assertEqual(1, len(got))
        self.assertIn('new', got[0][1])
        self.assertIn('Thumb', got[0][1])

    def test_one_that_went_says_gone(self):
        got = screens.save_rows(self.raw(self.ctrl('a', 'Thumb')),
                                self.raw())
        self.assertIn('gone', got[0][1])
        self.assertIn('Thumb', got[0][1])

    def test_and_one_that_moved_says_changed(self):
        got = screens.save_rows(
            self.raw(self.ctrl('a', 'Thumb')),
            self.raw(self.ctrl('a', 'Thumb', hold_ok=True)))
        self.assertIn('changed', got[0][1])

    def test_a_control_with_no_id_is_still_told_apart(self):
        # The uncaptured bucket has none, and two of them are not one.
        before = self.raw({'kind': 'unknown', 'states': [{'button': 1}]})
        after = self.raw({'kind': 'unknown', 'states': [{'button': 2}]})
        self.assertEqual(1, len(screens.save_rows(before, after)))

    def test_an_axis_that_moved_is_named(self):
        got = screens.save_rows(
            self.raw(axes=[{'index': 2, 'label': 'Left lever'}]),
            self.raw(axes=[{'index': 2, 'label': 'Left lever',
                            'moves_with': [3]}]))
        self.assertIn('Left lever', got[0][1])

    def test_what_the_hardware_reports_counts_too(self):
        got = screens.save_rows(self.raw(fingerprint={'buttons': 51}),
                                self.raw(fingerprint={'buttons': 52}))
        self.assertTrue(any('hardware' in t for _tone, t in got))

    def test_a_new_one_and_a_gone_one_are_both_listed(self):
        got = screens.save_rows(self.raw(self.ctrl('a', 'Thumb')),
                                self.raw(self.ctrl('b', 'Pinky')))
        said = '\n'.join(t for _tone, t in got)
        self.assertIn('Thumb', said)
        self.assertIn('Pinky', said)

    def test_an_axis_that_was_not_there_says_new(self):
        got = screens.save_rows(
            self.raw(), self.raw(axes=[{'index': 2, 'label': 'Left lever'}]))
        self.assertIn('new', got[0][1])
        self.assertIn('Left lever', got[0][1])

    def test_and_one_that_went_says_gone_by_name(self):
        got = screens.save_rows(
            self.raw(axes=[{'index': 2, 'label': 'Left lever'}]), self.raw())
        self.assertIn('gone', got[0][1])
        self.assertIn('Left lever', got[0][1])


class WhatSavingWouldChangeAboutTheDesk(unittest.TestCase):
    """In fingers walked and controls moved, not in spots: a spot is how
    the file says it, and `thumb, HOME` is what you did."""

    def rig(self, **kw):
        return {'device': [dict({'slug': 'a-stick'}, **kw)]}

    def test_nothing_moved_is_no_rows(self):
        one = self.rig(rounds=[{'level': 'HOME', 'finger': 'thumb'}])
        self.assertEqual([], screens.desk_rows(one, one, 'a-stick'))

    def test_a_finger_you_walked_says_so(self):
        got = screens.desk_rows(self.rig(),
                                self.rig(rounds=[{'level': 'HOME', 'finger': 'thumb'}]),
                                'a-stick')
        self.assertIn('walked', got[0][1])
        self.assertIn('thumb', got[0][1])

    def test_one_you_took_back_says_forgot(self):
        got = screens.desk_rows(self.rig(rounds=[{'level': 'HOME', 'finger': 'thumb'}]),
                                self.rig(), 'a-stick')
        self.assertIn('forgot', got[0][1])

    def test_controls_that_moved_are_counted(self):
        got = screens.desk_rows(
            self.rig(),
            self.rig(access={'a': [{'level': 'HOME'}],
                             'b': [{'level': 'OFF'}]}), 'a-stick')
        self.assertTrue(any('2 controls' in t for _tone, t in got), got)

    def test_which_hand_is_on_it_counts_too(self):
        got = screens.desk_rows(self.rig(hand='left'),
                                self.rig(hand='right'), 'a-stick')
        self.assertTrue(any('hand' in t for _tone, t in got), got)

    def test_another_device_on_the_same_desk_is_not_this_one(self):
        before = {'device': [{'slug': 'a-stick'},
                             {'slug': 'a-throttle', 'rounds': []}]}
        after = {'device': [{'slug': 'a-stick'},
                            {'slug': 'a-throttle',
                             'rounds': [{'level': 'HOME', 'finger': 'thumb'}]}]}
        self.assertEqual([], screens.desk_rows(before, after, 'a-stick'))

    def test_a_desk_that_did_not_name_it_before_is_all_new(self):
        got = screens.desk_rows({'device': []},
                                self.rig(rounds=[{'level': 'HOME', 'finger': 'thumb'}]),
                                'a-stick')
        self.assertEqual(1, len(got))
        self.assertIn('walked', got[0][1])




class TheWholeHandReachesThingsToo(unittest.TestCase):
    """A stick, a throttle handle, a wheel: worked by moving the lot, so
    no finger round could ever find them -- and the rule that what no
    round reached is off the device then wrote `let go to reach it`
    about the thing being held."""

    def setUp(self):
        self.sheet = q.read()
        self.dev = fake.devices()[0]
        self.rounds = screens.reach_rounds(self.dev, fake.rig(self.dev),
                                           self.sheet.vocabulary['level'])

    def test_it_is_one_of_the_things_that_reach(self):
        self.assertIn(devicemap.HAND, devicemap.FINGERS)

    def test_a_round_for_it_at_every_posture(self):
        hands = [r for r in self.rounds if r.finger == devicemap.HAND]
        self.assertEqual(len(self.sheet.vocabulary['level']), len(hands))

    def test_it_is_called_something_on_the_list(self):
        rows = screens.reach_rows(self.rounds)
        said = [t for tone, t in rows if tone != 'subhead']
        self.assertTrue(any('whole hand' in t for t in said), said[:3])

    def test_and_never_left_blank(self):
        for tone, text in screens.reach_rows(self.rounds):
            if tone != 'subhead':
                with self.subTest(row=text):
                    self.assertTrue(text.strip())

    def test_its_screen_does_not_ask_for_a_finger(self):
        one = next(r for r in self.rounds if r.finger == devicemap.HAND)
        title, aside, says = screens.round_prompt(one)
        self.assertIn('whole hand', title)
        # `not a finger` is the whole distinction: you do not reach a
        # stick with your hand, you hold it and move the lot.
        self.assertIn('not a finger', says)
        self.assertNotIn('the the', says)
        # And a finger round asks for that finger, not for the hand.
        thumb = next(r for r in self.rounds if r.finger == 'thumb')
        self.assertIn('thumb', screens.round_prompt(thumb)[2])
        self.assertNotIn('whole hand', screens.round_prompt(thumb)[2])

    def test_nor_repeat_a_hint_that_says_nothing_moves(self):
        # The posture's hint is about a finger going somewhere from a
        # hand that stayed put, and this round moves the hand.
        one = next(r for r in self.rounds if r.finger == devicemap.HAND)
        _title, aside, _says = screens.round_prompt(one)
        for said in one.level.get('hint') or []:
            self.assertNotIn(said, aside)

    def test_a_finger_round_keeps_its_hint(self):
        one = next(r for r in self.rounds if r.finger == 'thumb')
        _title, aside, _says = screens.round_prompt(one)
        for said in one.level.get('hint') or []:
            self.assertIn(said, aside)

    def test_what_it_found_is_read_back_from_a_spot_with_no_finger(self):
        # The writer leaves an empty finger out, so the spot comes back
        # with no key at all and a plain `==` never matched it.
        one = next(g for g in self.dev.groups(bindable=True) if g.id)
        lvl = self.sheet.vocabulary['level'][0]
        rig = devicemap.Profile({'name': 'x', 'device': [
            {'slug': self.dev.slug,
             'rounds': [{'level': lvl['name']}],
             'access': {one.id: [{'level': lvl['name']}]}}]},
            '<x>')
        got = next(r for r in screens.reach_rounds(
            self.dev, rig, self.sheet.vocabulary['level'])
            if r.finger == devicemap.HAND and r.level is lvl)
        self.assertEqual([one.id], got.found)
        self.assertTrue(got.done)


class TheCornerAnswersAnAxisToo(unittest.TestCase):
    """It answered presses and said nothing about axes, so moving a
    throttle lever -- the one thing on a throttle you cannot press to
    find out what it is -- left you where you started."""

    def dev(self):
        return fake.device(kind='throttle', axes=[
            fake.axis(0, role='x'), fake.axis(1, role='y'), fake.axis(2)],
            groups=[fake.group('ministick', [], label='Thumb stick',
                               id='thumb-stick', axes=[0, 1]),
                    fake.group('lever', [], label='Left lever',
                               id='left-lever', axes=[2])])

    def said(self, index, called=''):
        return '\n'.join(t for _tone, t in
                         screens.what_moved(self.dev(), index, called))

    def test_it_names_the_control_the_axis_belongs_to(self):
        self.assertIn('Left lever', self.said(2))
        self.assertIn('axis 2', self.said(2))

    def test_and_which_axis_of_it_where_there_is_more_than_one(self):
        self.assertIn('horizontal', self.said(0, 'horizontal'))

    def test_the_row_it_points_at_is_the_control_row(self):
        dev = self.dev()
        rows = screens.control_rows(dev.under(None))
        at = screens.row_of_axis(rows, dev, 1)
        assert at is not None
        self.assertIs(dev.axis_group(1), rows[at].group)

    def test_both_axes_of_one_control_point_at_the_same_row(self):
        dev = self.dev()
        rows = screens.control_rows(dev.under(None))
        self.assertEqual(screens.row_of_axis(rows, dev, 0),
                         screens.row_of_axis(rows, dev, 1))


class TheColumnsAreNamed(unittest.TestCase):
    """A heading pinned in the frame, not the first row of the list: one
    that scrolls away is one you have to remember, and one you can put
    the cursor on is a row."""

    def setUp(self):
        self.dev = fake.devices()[0].under(None)

    def test_a_name_for_every_column_a_row_has(self):
        head = screens.control_head()
        for _wide, said in screens.COLUMNS:
            if said:
                with self.subTest(column=said):
                    self.assertIn(said, head)

    def test_it_lines_up_with_the_rows(self):
        # The same widths, from the same tuple: a heading that does not
        # sit over its column is worse than none.
        head = screens.control_head()
        for row in screens.control_rows(self.dev):
            if row.group is None or not row.group.bindable:
                continue
            with self.subTest(row=row.text):
                for n in (1, 2, 3):
                    at = sum(w + 1 for w, _s in screens.COLUMNS[:n])
                    self.assertTrue(head[at:].startswith(
                        screens.COLUMNS[n][1]))
                    self.assertNotEqual(' ', row.text[at:at + 1] or 'x')

    def test_it_fits_the_screen_the_list_is_drawn_on(self):
        scr = fake.Screen(24, 80)
        t = ui.Tui(scr, ui.Theme(False))
        room = ui.text_in(*ui.box_for([], 24, 80, 'x', True)[1::2])[1]
        self.assertLessEqual(len(screens.control_head()), room)
