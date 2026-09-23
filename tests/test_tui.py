"""The frame a panel is drawn in, as strings.

The chrome lives in the border: the title, the counts and the key names all
sit in the box edge rather than in rows of their own. That is the whole
reason to have a frame -- three rows of key names at the bottom of a 24-row
terminal is an eighth of the screen spent on something you read once.

The builders here are pure, and that is the point. The last two attempts at
chrome in this family drew one thing over another and every test passed,
because they all asked what the text said rather than what reached the
screen. A string cannot paint over itself.

Nothing here opens a terminal. `Theme` reads curses' attribute constants,
which exist without one.
"""

import curses
import unittest

import fake
import tui


class TheTopEdge(unittest.TestCase):
    def test_it_is_exactly_as_wide_as_asked(self):
        for w in range(1, 60):
            with self.subTest(w=w):
                self.assertEqual(w, len(tui.lid(w, 'title', '3 of 9')))

    def test_the_title_sits_in_the_border(self):
        got = tui.lid(30, 'Main trigger')
        self.assertIn(' Main trigger ', got)
        self.assertTrue(got.startswith(tui.TL))
        self.assertTrue(got.endswith(tui.TR))

    def test_the_count_sits_on_the_right(self):
        got = tui.lid(40, 'Main trigger', '5 of 8')
        self.assertLess(got.index('Main trigger'), got.index('5 of 8'))

    def test_a_count_that_will_not_fit_is_dropped_whole(self):
        # Not half of it. A border that has eaten half a number says less
        # than a plain one.
        got = tui.lid(20, 'a rather long title', '5 of 8')
        self.assertNotIn('5', got)

    def test_a_title_that_will_not_fit_is_cut_not_wrapped(self):
        got = tui.lid(12, 'an extremely long title indeed')
        self.assertEqual(12, len(got))

    def test_a_border_too_narrow_for_anything(self):
        self.assertEqual('', tui.lid(0))
        self.assertEqual(tui.H, tui.lid(1))
        self.assertEqual(tui.TL + tui.TR, tui.lid(2))


class TheBottomEdge(unittest.TestCase):
    def test_it_is_exactly_as_wide_as_asked(self):
        for w in range(1, 60):
            with self.subTest(w=w):
                self.assertEqual(w, len(tui.sill(w, ('↑↓ move', '↵ choose'),
                                                 '3 of 9')))

    def test_the_keys_sit_in_the_border(self):
        got = tui.sill(40, ('↑↓ move', '↵ choose'))
        self.assertIn('↑↓ move', got)
        self.assertIn(tui.SEP.strip(), got)

    def test_keys_are_dropped_from_the_end(self):
        # The list is written most-needed first: without the first one
        # nothing else on the screen is reachable.
        got = tui.sill(22, ('↑↓ move', '↵ choose', 'ESC back', 'q quit'))
        self.assertIn('↑↓ move', got)
        self.assertNotIn('q quit', got)

    def test_the_count_is_kept_before_any_of_them(self):
        got = tui.sill(24, ('↑↓ move', '↵ choose', 'ESC back'), '9 of 40')
        self.assertIn('9 of 40', got)

    def test_a_note_takes_the_left_and_the_keys_give_way(self):
        # A status line is the one thing down here that changes, so it goes
        # IN the edge rather than being drawn over it.
        got = tui.sill(40, ('↑↓ move', '↵ choose'), note='nothing to capture')
        self.assertIn('nothing to capture', got)
        self.assertNotIn('↑↓ move', got)
        self.assertEqual(40, len(got))


class HangingText(unittest.TestCase):
    def test_a_continuation_line_hangs_under_the_lead(self):
        got = tui.fit(24, 'shape and count both fit the need', lead='  +40 ')
        self.assertTrue(got[0].startswith('  +40 '))
        self.assertTrue(all(ln.startswith(' ' * 6) for ln in got[1:]))

    def test_nothing_is_wider_than_asked(self):
        got = tui.fit(24, 'shape and count both fit the need', lead='  +40 ')
        self.assertTrue(all(len(ln) <= 24 for ln in got), got)

    def test_empty_text_is_still_a_line(self):
        self.assertEqual([''], tui.fit(20, ''))


class HowBigABox(unittest.TestCase):
    def test_a_short_list_gets_a_box_its_own_size(self):
        # Two lines, a lid, a sill, and a blank row above the sill.
        _y, _x, bh, _bw = tui.box_for(['one', 'two'], 24, 80)
        self.assertEqual(5, bh)

    def test_the_text_does_not_touch_the_bottom_edge(self):
        # A line pressed against the edge reads as one that ran out of
        # room rather than one that ended.
        for n in (1, 3, 9):
            with self.subTest(lines=n):
                _y, _x, bh, _bw = tui.box_for(['x'] * n, 24, 80)
                self.assertEqual(n + 3, bh)

    def test_a_long_list_stops_at_the_screen(self):
        _y, _x, bh, _bw = tui.box_for([f'line {i}' for i in range(90)], 24, 80)
        self.assertLessEqual(bh, 24)

    def test_a_dialog_is_one_width_whatever_it_holds(self):
        # Fitted to its longest line, a dialog is a different size every
        # time, and answering down a list becomes a frame that jumps about
        # under the cursor.
        wide = tui.box_for(['a' * 50], 24, 80)[3]
        narrow = tui.box_for(['yes'], 24, 80)[3]
        self.assertEqual(wide, narrow)

    def test_a_long_line_folds_rather_than_widening_the_box(self):
        bw = tui.box_for(['a ' * 90], 24, 80)[3]
        self.assertEqual(tui.box_for(['yes'], 24, 80)[3], bw)
        self.assertGreater(len(tui.wrapped(['a ' * 90], bw)), 1)

    def test_a_title_too_long_for_the_width_still_gets_it(self):
        bw = tui.box_for(['x'], 24, 120, 'a title longer than any dialog '
                                         'has a right to be, and then some')
        self.assertGreater(bw[3], tui.DIALOG)

    def test_the_text_does_not_touch_the_border(self):
        # One blank column reads as the text having been squeezed in: the
        # border stops being a frame and becomes an edge the words are up
        # against. Both sides, or it reads as lopsided instead.
        self.assertGreaterEqual(tui.GAP, 2)

    def test_the_gap_is_on_both_sides(self):
        # A gap on the right and none on the left draws exactly as well as
        # a correct one, and reads as lopsided.
        _y, x, _bh, bw = tui.box_for(['a' * 30], 24, 80)
        at, room = tui.text_in(x, bw)
        self.assertEqual(tui.GAP, at - x - 1)
        self.assertEqual(tui.GAP, (x + bw - 1) - (at + room))

    def test_a_box_too_narrow_for_a_gap_still_shows_something(self):
        at, room = tui.text_in(0, 4)
        self.assertGreaterEqual(room, 1)
        self.assertGreater(at, 0)

    def test_a_long_title_widens_it(self):
        _y, _x, _bh, bw = tui.box_for(['x'], 24, 80, 'a title of some length')
        self.assertGreater(bw, len('a title of some length'))

    def test_it_is_centred(self):
        y, x, bh, bw = tui.box_for(['one'], 24, 80)
        self.assertEqual((24 - bh) // 2, y)
        self.assertEqual((80 - bw) // 2, x)

    def test_full_takes_every_row_and_all_but_one_column(self):
        # A notice you read wants to be the size of what it says; a list you
        # work in wants every row, and centring costs two of them. The one
        # column is the terminal's: its bottom-right cell cannot be written,
        # and a sill that runs to the edge loses its corner to that.
        self.assertEqual((0, 0, 24, 79), tui.box_for(['one'], 24, 80,
                                                     full=True))

    def test_overflowing_is_about_the_page_not_the_screen(self):
        self.assertFalse(tui.overflows(['one', 'two'], 24, 80))
        self.assertTrue(tui.overflows([f'{i}' for i in range(40)], 24, 80))


class HowMuchFitsOnAScreen(unittest.TestCase):
    """A box costs a lid and a sill, and is capped two rows short of the
    screen on top of that. Counting one pair and not the other builds a list
    longer than the box that holds it, and the overflow is silent."""

    def test_a_list_and_its_box_fit_the_screen(self):
        for h in range(6, 60):
            for extra in (0, 2, 5, 9):
                with self.subTest(h=h, extra=extra):
                    room, spare = tui.page_room(h, extra)
                    _y, _x, bh, _bw = tui.box_for(['x'] * (room + spare), h, 80)
                    self.assertLessEqual(room + spare, bh - 2)

    def test_a_hint_under_the_list_costs_the_list_those_rows(self):
        self.assertEqual((tui.page_room(24)[0] - 3, 3), tui.page_room(24, 3))

    def test_a_hint_that_will_not_fit_is_dropped_whole(self):
        # Half a hint is worse than no hint, and a list you cannot move in
        # is worse than an explanation you cannot read.
        room, spare = tui.page_room(9, 6)
        self.assertEqual(0, spare)
        self.assertGreaterEqual(room, 3)

    def test_a_terminal_too_short_shows_what_it_can(self):
        # Below the floor the screen wins: three rows drawn into a two-row
        # box is the silent overflow this exists to stop.
        room, spare = tui.page_room(6, 8)
        self.assertEqual(0, spare)
        self.assertGreaterEqual(room, 1)


class WhatIsLeftUnderABox(unittest.TestCase):
    """A box drawn over a wider one left that one's edges around it, and
    the two together read as two dialogs open at once."""

    def drawn(self, *boxes):
        scr = fake.Screen()
        t = tui.Tui(scr, tui.Theme(False))
        for title, lines, kw in boxes:
            t.box(title, [('plain', ln) for ln in lines], **kw)
        return scr.text()

    def test_the_list_stays_visible_under_a_dialog(self):
        # Clearing outright loses sight of what you are working down, and
        # that is worse than the debris it was meant to stop.
        got = self.drawn(
            ('device', [f'control {i}' for i in range(8)], {'full': True}),
            ('values', ['high', 'low'], {}))
        self.assertIn('values', got)
        self.assertIn('control 0', got)

    def test_one_dialog_leaves_nothing_of_the_one_before_it(self):
        got = self.drawn(
            ('device', [f'control {i}' for i in range(8)], {'full': True}),
            ('which one', ['a question at some length'], {}),
            ('values', ['high', 'low'], {}))
        self.assertIn('values', got)
        self.assertIn('control 0', got)
        self.assertNotIn('which one', got)
        self.assertNotIn('a question', got)

    def test_a_dialog_sits_on_the_screen_it_was_opened_from(self):
        # Two panels are also something you open a dialog from, and what
        # came before them is not what you are looking at.
        scr = fake.Screen(16, 80, keys=[27])
        t = tui.Tui(scr, tui.Theme(False))
        t.box('device', [('plain', f'control {i}') for i in range(8)],
              full=True)
        t.browse('reach', [('plain', 'in the grip'), ('plain', 'thumb')],
                 lambda n: ('thumb', [('plain', 'press it')]))
        t.box('press what it reaches', [('plain', 'then RETURN')])
        got = scr.text()
        self.assertIn('then RETURN', got)
        self.assertIn('in the grip', got)
        self.assertNotIn('control 0', got)

    def test_the_backdrop_is_not_cut_mid_word(self):
        # The list behind runs up to the frame otherwise, and half a word
        # beside a border reads as something broken rather than behind.
        got = self.drawn(
            ('device', ['control ' + 'x' * 60 for _ in range(8)],
             {'full': True}),
            ('values', ['high', 'low'], {}))
        for line in got.splitlines():
            if tui.TL in line or tui.BL in line:
                at = max(line.find(tui.TL), line.find(tui.BL))
                if at > 1:
                    with self.subTest(line=line):
                        self.assertEqual(' ', line[at - 1])

    def test_the_box_that_is_up_is_whole(self):
        got = self.drawn(
            ('device', ['a' * 60], {'full': True}),
            ('values', ['high'], {}))
        first = [ln for ln in got.splitlines() if ln.strip()][0]
        self.assertTrue(first.lstrip().startswith(tui.TL), first)
        self.assertTrue(first.rstrip().endswith(tui.TR), first)


class TheCornerBox(unittest.TestCase):
    """It answers a question about the list behind it, so hiding the list
    would be answering into an empty room."""

    def drawn(self, lines, title='pressed', wide=False):
        # Wide rows on purpose where the margin is what is under test: a
        # short list never reaches the corner, so nothing is cut and the
        # clearing has nothing to do.
        scr = fake.Screen(12, 70)
        t = tui.Tui(scr, tui.Theme(False))
        said = (f'control {i} ' + 'x' * 50 if wide else f'control {i}'
                for i in range(8))
        t.box('device', [('plain', x) for x in said],
              ('q quit',), 'x', full=True)
        t.corner(title, lines)
        return scr.text()

    def test_it_says_what_it_was_given(self):
        got = self.drawn([('plain', 'js 5'), ('plain', 'Middle finger hat')])
        self.assertIn('pressed', got)
        self.assertIn('Middle finger hat', got)

    def test_the_list_is_still_there(self):
        got = self.drawn([('plain', 'js 5')])
        self.assertIn('control 0', got)
        self.assertIn('device', got)

    def test_it_sits_in_the_bottom_right(self):
        got = self.drawn([('plain', 'js 5')]).splitlines()
        rows = [n for n, ln in enumerate(got) if 'js 5' in ln]
        self.assertGreater(rows[0], len(got) // 2)
        self.assertGreater(got[rows[0]].index('js 5'), 35)

    def test_nothing_to_say_draws_nothing(self):
        self.assertNotIn('pressed', self.drawn([]))

    def test_the_list_is_not_cut_against_its_frame(self):
        got = self.drawn([('plain', 'js 5')], wide=True)
        for line in got.splitlines():
            at = line.find(tui.TL, 1)
            if at > 1:
                with self.subTest(line=line):
                    self.assertEqual(' ', line[at - 1])


class ATwoLevelTree(unittest.TestCase):
    def test_the_last_one_is_closed_off(self):
        got = tui.tree([('meta', 'reach 0'), ('plain', '177 points')])
        self.assertIn(tui.BRANCH, got[0][1])
        self.assertIn(tui.LAST, got[1][1])

    def test_one_child_is_already_the_last(self):
        got = tui.tree([('plain', 'only')])
        self.assertIn(tui.LAST, got[0][1])

    def test_each_row_keeps_its_own_tone(self):
        got = tui.tree([('meta', 'a'), ('note', 'b')])
        self.assertEqual(['meta', 'note'], [tone for tone, _ in got])


class Counting(unittest.TestCase):
    def test_one_of_a_thing(self):
        self.assertEqual('1 position', tui.plural(1, 'position'))

    def test_several(self):
        self.assertEqual('3 positions', tui.plural(3, 'position'))

    def test_none_is_plural(self):
        self.assertEqual('0 positions', tui.plural(0, 'position'))

    def test_a_word_that_does_not_take_an_s(self):
        self.assertEqual('2 entries', tui.plural(2, 'entry', 'entries'))


class Tones(unittest.TestCase):
    """Named for what a thing IS, never for the colour it comes out as."""

    def test_without_colour_everything_still_reads(self):
        t = tui.Theme(colour=False)
        self.assertEqual(curses.A_BOLD, t.head)
        self.assertEqual(curses.A_DIM, t.meta)
        self.assertEqual(curses.A_REVERSE, t.sel)

    def test_a_line_can_carry_its_own_tone_by_name(self):
        t = tui.Theme(colour=False)
        self.assertEqual(t.measured, t['measured'])

    def test_the_ladder_is_three_distinct_steps(self):
        # head, subhead and meta are meant to be read as one ladder: the
        # section, the thing it names, and the detail under it. A listing
        # that puts all three in the same weight has to be read from the top.
        t = tui.Theme(colour=False)
        self.assertEqual(3, len({t.head, t.subhead, t.meta}))

    def test_the_cursor_is_a_tone_and_not_a_character(self):
        # Every glyph in this module means something that stays put. Where
        # you are is the one thing that moves, and it is reverse video.
        t = tui.Theme(colour=False)
        self.assertEqual(curses.A_REVERSE, t.sel)
        for glyph in (tui.TL, tui.TR, tui.BL, tui.BR, tui.V, tui.H,
                      tui.BRANCH, tui.LAST):
            with self.subTest(glyph=glyph):
                self.assertNotIn(glyph, '▸>*')


if __name__ == '__main__':
    unittest.main()

class WhatTheDetailPanelCounts(unittest.TestCase):
    """The panel's edge counts rows by default, and a list with headings
    in it has more rows than things."""

    def browse(self, **kw):
        scr = fake.Screen(14, 80, keys=[27])     # ESC: one draw and out
        t = tui.Tui(scr, tui.Theme(False))
        t.browse('list', [('plain', 'one'), ('plain', 'two')],
                 lambda n: ('side', [('plain', 'what')]), **kw)
        return scr.text()

    def test_by_default_it_counts_the_rows(self):
        self.assertIn('1 of 2', self.browse())

    def test_what_it_counts_can_be_said_by_the_caller(self):
        self.assertIn('round 4', self.browse(count=lambda n: 'round 4'))

    def test_a_caller_can_have_it_count_nothing(self):
        said = self.browse(count=lambda n: '')
        self.assertIn('side', said)
        self.assertNotIn('1 of 2', said)
