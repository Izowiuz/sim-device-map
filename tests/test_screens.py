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
        said = {'top-hat': [{'part': 'stick', 'level': 'HOME',
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
        self.assertIn('5 facts to go', row.text)

    def test_answered_for(self):
        row = self.rows(hold_ok=True, rapid_ok=True,
                                   modifier_ok=False, blind_distinct='high',
                                   accident_risk='low')[0]
        self.assertEqual('measured', row.tone)
        self.assertNotIn('to go', row.text)

    def test_one_answer_short_is_not_finished(self):
        row = self.rows(hold_ok=True, rapid_ok=True,
                                    modifier_ok=False,
                                    blind_distinct='high')[0]
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
        dev = fake.device(groups=[fake.group('unknown', [6, 7, 8],
                                             label='Not yet captured')])
        rows = screens.control_rows(dev.under(None))
        self.assertEqual([6, 7, 8], [r.button for r in rows])
        for row in rows:
            with self.subTest(row=row.text):
                self.assertIn('not described yet', row.text)
                self.assertNotIn('position', row.text)
                self.assertNotIn('tier', row.text)

    def test_a_loose_button_says_which_one_it_is(self):
        dev = fake.device(groups=[fake.group('unknown', [19])])
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
        for kind in screens.NOT_A_CONTROL:
            if kind == 'unknown':
                continue            # a row each, not one row: see above
            dev = fake.device(groups=[fake.group(kind, [1, 2], label='',
                                                 id=kind)])
            row = screens.control_rows(dev.under(None))[0]
            with self.subTest(kind=kind):
                self.assertIn(screens.NOT_A_CONTROL[kind][0], row.text)
                self.assertIn('js 1, 2', row.text)
                # Not a control, so neither of the columns that are about
                # controls: it has no positions and nothing reaches it.
                self.assertIn('2 buttons', row.text)
                self.assertNotIn('position', row.text)
                self.assertNotIn('tier', row.text)
                self.assertNotIn('reach', row.text)

    def test_a_control_with_nothing_behind_it_is_asked_nothing(self):
        dev = fake.device(groups=[fake.group('unwired', [1, 2],
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
        self.dev = fake.devices()[0]
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
            rapid_ok=True, modifier_ok=True, blind_distinct='high',
            accident_risk='low')])
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
            rapid_ok=True, modifier_ok=True, blind_distinct='high',
            accident_risk='low')])
        _head, said = screens.fact_side(dev.under(None), self.asks, 0)
        shown = [t for tone, t in said if tone == screens.TONE['measured']]
        self.assertTrue(shown, said)
        with_left = screens.fact_side(self.dev, self.asks, 0)[1]
        self.assertNotEqual([t for tone, t in with_left
                             if tone == screens.TONE['measured']], shown)


class AnsweringOneFact(unittest.TestCase):
    def setUp(self):
        self.sheet = q.read()
        self.dev = fake.devices()[0]
        self.ctrls = [g for g in self.dev.groups(bindable=True) if g.id]

    def ask(self, sets):
        return next(a for a in self.sheet.of(q.ALL) if a.sets == sets)

    def test_one_row_per_control(self):
        rows = screens.answer_rows(self.dev, self.ask('hold_ok'), self.ctrls)
        self.assertEqual(len(self.ctrls), len(rows))

    def test_a_yes_and_a_no_do_not_read_alike(self):
        self.assertNotEqual(screens.SAID[True], screens.SAID[False])

    def test_a_row_says_the_answer_and_what_it_is_about_and_no_more(self):
        # How far away the control is used to ride along here. It is true
        # and beside the point: the question is about the feel of the
        # thing under your finger, and it was a column to read past on
        # every row of twenty-six.
        for ask in self.sheet.of(q.ALL):
            rows = screens.answer_rows(self.dev, ask, self.ctrls)
            for g, (_tone, text) in zip(self.ctrls, rows):
                got = g.fact(ask.sets)
                mark = ('' if got is None
                        else screens.SAID[got] if isinstance(got, bool)
                        else str(got))
                with self.subTest(ctrl=g.id, ask=ask.id):
                    self.assertEqual(
                        mark, text.replace(g.label or g.kind, '').strip())

    def test_a_row_shows_a_mark_and_not_python(self):
        ask = self.ask('hold_ok')
        one = self.ctrls[0]
        one.hold_ok = True
        try:
            rows = screens.answer_rows(self.dev, ask, self.ctrls)
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
        rows = screens.answer_rows(self.dev, self.ask('hold_ok'), self.ctrls)
        for g, (_tone, text) in zip(self.ctrls, rows):
            if g.told('hold_ok') == 'missing':
                with self.subTest(ctrl=g.id):
                    self.assertNotIn(screens.SAID[True], text)
                    self.assertNotIn(screens.SAID[False], text)

    def test_a_three_step_row_shows_the_value_it_has(self):
        ask = self.ask('blind_distinct')
        names = [c['name'] for c in self.sheet.choices(ask)]
        one = self.ctrls[0]
        one.blind_distinct = names[0]
        try:
            (_tone, text), *_ = screens.answer_rows(self.dev, ask, self.ctrls)
        finally:
            one.blind_distinct = ''
        self.assertTrue(text.startswith(names[0]), text)

    def test_an_answer_reads_as_a_word_and_not_as_python(self):
        _head, said = screens.answer_side(self.dev, self.ask('hold_ok'),
                                          self.ctrls, 0)
        shown = '\n'.join(t for _tone, t in said)
        self.assertNotIn('True', shown)
        self.assertNotIn('False', shown)
        self.assertRegex(shown, r'\b(yes|no)\b')

    def test_every_note_reaches_the_panel_whole(self):
        for ask in self.sheet.of(q.ALL):
            _head, said = screens.answer_side(self.dev, ask, self.ctrls, 0)
            shown = [t for _tone, t in said]
            for para in screens.note_lines(ask):
                with self.subTest(ask=ask.id):
                    self.assertIn(para, shown)

    def test_it_carries_the_answer_and_the_sentences_and_no_more(self):
        # How many positions it has and how far away it is are true and
        # beside the point: the question is about the feel of the thing.
        ask = self.ask('hold_ok')
        _head, said = screens.answer_side(self.dev, ask, self.ctrls, 0)
        shown = [t for _tone, t in said if t]
        want = [ask.says] + screens.note_lines(ask)
        self.assertEqual(len(want) + 1, len(shown), shown)
        self.assertNotIn('tier', ' '.join(shown))
        self.assertNotIn('position', ' '.join(shown))

    def test_no_answer_says_so_rather_than_showing_one(self):
        ask = self.ask('hold_ok')
        self.assertEqual('missing', self.ctrls[0].told(ask.sets))
        _head, said = screens.answer_side(self.dev, ask, self.ctrls, 0)
        shown = '\n'.join(t for _tone, t in said)
        self.assertNotIn('yes', shown.split(ask.says)[0])
        self.assertIn('no answer', shown)

    def test_the_control_comes_before_the_question(self):
        # The title already names it; what you want next is its answer,
        # not the question you have read twenty-five times.
        ask = self.ask('hold_ok')
        head, said = screens.answer_side(self.dev, ask, self.ctrls, 0)
        shown = [t for _tone, t in said]
        self.assertEqual(self.ctrls[0].label, head)
        self.assertLess(shown.index(screens._answer_said(
            self.ctrls[0].fact(ask.sets))), shown.index(ask.says))

    def test_it_does_not_repeat_what_the_border_says(self):
        # The keys are in the sill. Saying them again costs two rows of
        # the note, which is the half that tells you how to answer.
        _head, said = screens.answer_side(self.dev, self.ask('hold_ok'),
                                          self.ctrls, 0)
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

    def fits(self, rows):
        for _tone, text in rows:
            with self.subTest(row=text):
                self.assertLessEqual(len(text), self.room)

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
        controls = [g for g in self.dev.groups(bindable=True) if g.id]
        for ask in self.sheet.of(q.ALL):
            self.fits(screens.answer_rows(self.dev, ask, controls))

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
                self.assertFalse(m.device.unknown()[0])
                self.assertIn(f'{done}/{total}', text)
                self.assertNotIn(f'{m.device.n_buttons}/'
                                 f'{m.device.n_buttons}', text)

    def test_a_device_nobody_has_touched_counts_its_buttons(self):
        # Controls are made by pressing buttons, so a fresh device has
        # none of them -- and a ratio of them is 0 of 0, which reads as
        # finished. Buttons come from the firmware and are there at once.
        fresh = fake.device(groups=[fake.group('unknown', [0, 1, 2, 3])])
        (tone, text), = screens.found_rows([self.Plugged(fresh)])
        self.assertIn('4 buttons', text)
        self.assertNotIn('0/0', text)
        self.assertNotEqual(screens.TONE['measured'], tone)

    def test_and_says_so_in_the_hint_as_well(self):
        fresh = fake.device(groups=[fake.group('unknown', [0, 1, 2, 3])])
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
        fresh = fake.device(groups=[fake.group('unknown', [0, 1, 2, 3])])
        said = ' '.join(screens.found_hints(self.Plugged(fresh))).lower()
        self.assertNotIn('nothing outstanding', said)

    def test_a_device_with_nothing_left_says_so(self):
        done = fake.device(groups=[fake.group(
            'button', [0], label='One', id='one', hold_ok=True,
            rapid_ok=True, modifier_ok=True, blind_distinct='high',
            accident_risk='low')])
        done.under(devicemap.Profile({'name': 'x', 'device': [{
            'slug': done.slug, 'hand': 'left',
            'access': {'one': [{'part': 'stick', 'level': 'HOME',
                                'finger': 'thumb'}]}}]}, '<test>'))
        said = ' '.join(screens.found_hints(self.Plugged(done))).lower()
        self.assertIn('nothing outstanding', said)

    def test_buttons_first_and_answers_after(self):
        # One job at a time: sorting the buttons into controls comes
        # before anything can be asked about a control.
        half = fake.device(groups=[fake.group('unknown', [0]),
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
                    said = screens._owns(g)
                    self.assertIn('axis' if len(g.axes) == 1 else 'axes',
                                  said)
                    self.assertNotIn('0', said)

    def test_a_control_with_positions_counts_them(self):
        for g in self.dev.groups(bindable=True):
            if g.places:
                with self.subTest(ctrl=g.id):
                    self.assertIn(ui.plural(len(g.places), 'position'),
                                  screens._owns(g))

    def test_a_control_with_only_a_click_says_so(self):
        # Otherwise its row says nothing at all about what is on it.
        for g in self.dev.groups(bindable=True):
            if g.push is not None and not g.places:
                with self.subTest(ctrl=g.id):
                    self.assertIn('click', screens._owns(g))

    def test_a_pile_of_buttons_is_counted_in_buttons(self):
        for g in self.dev.groups():
            if not g.bindable and g.all_buttons:
                with self.subTest(kind=g.kind):
                    self.assertIn('button', screens._owns(g))
                    self.assertNotIn('position', screens._owns(g))


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
        said['access'] = {one.id: [{'part': self.dev.kind,
                                    'level': lvl['name'],
                                    'finger': 'thumb'}]}
        rig = devicemap.Profile({'name': 'x', 'device': [said]}, '<test>')
        rounds = screens.reach_rounds(self.dev, rig,
                                      self.sheet.vocabulary['level'])
        got = next(r for r in rounds
                   if r.finger == 'thumb' and r.level is lvl)
        self.assertEqual([one.id], got.found)
        self.assertFalse(got.done)

        said['rounds'] = [[lvl['name'], 'thumb']]
        rig = devicemap.Profile({'name': 'x', 'device': [said]}, '<test>')
        rounds = screens.reach_rounds(self.dev, rig,
                                      self.sheet.vocabulary['level'])
        self.assertTrue(next(r for r in rounds if r.finger == 'thumb'
                             and r.level is lvl).done)

    def test_a_long_round_does_not_run_off_the_panel(self):
        lvl = self.sheet.vocabulary['level'][0]
        every = [g.id for g in self.dev.groups(bindable=True) if g.id]
        self.assertGreater(len(every), screens.SHOWN)
        _h, said = screens.reach_side(
            self.dev, [screens.Round(lvl, 'thumb', every, True)], 1, [])
        shown = [t for _tone, t in said]
        self.assertTrue(any(f'{len(every) - screens.SHOWN} more' in t
                            for t in shown))

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
        one = rounds[0]
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
        self.assertIn(screens.NOT_A_CONTROL['unknown'][0], said)

    def test_it_finds_the_row_the_button_is_on(self):
        dev = self.dev()
        rows = screens.control_rows(dev)
        g = next(x for x in dev.groups(bindable=True) if x.label)
        at = screens.row_of(rows, dev, g.buttons[0])
        assert at is not None
        self.assertIs(g, rows[at].group)

    def test_a_loose_button_finds_its_own_row(self):
        dev = fake.device(groups=[fake.group('unknown', [6, 7, 8])])
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
        dev = fake.device(groups=[fake.group('unwired', [1, 2], id='u')])
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
        for k, _says, what in screens.DESK_KEYS:
            with self.subTest(key=k):
                self.assertEqual(1, said.count(what))


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
