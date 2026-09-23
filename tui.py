"""The curses shell every screen here is drawn on.

    tui = setup(scr)
    tui.menu('what is it?', items, hints)
    tui.popup('device map', lines, full=True)

The chrome lives in the border. A title, a count and a list of key names all
fit in the box edge, so none of them costs a row -- and three rows of key
names at the bottom of a 24-row terminal is an eighth of the screen spent on
something you read once.

Where you are is a tone, never a character. `theme.sel` marks the cursor, and
the glyphs are kept for things that stay put: a mark against a row, a branch
in a tree, the divider between two columns. A screen that says "you are here"
twice, once in reverse video and once with an arrow, has taught you two ways
to read the same thing.

The measuring functions -- `lid`, `sill`, `fit`, `box_for` -- are pure and
return strings or rectangles. That is what makes them testable: the last two
attempts at chrome in this family drew one thing over another and every test
passed, because they asked what the text said rather than what reached the
screen. A string cannot paint over itself.

This is a deliberate copy of `sim-bind-wizard/core/tui.py`, not an import.
The dependency runs the other way -- that repo reads this map -- so it cannot
be the one to hold the shell both of them draw on.
"""

import curses
from functools import partial
import textwrap
import time


class Theme:
    """What each meaning on the screen looks like, worked out once.

    Tones are named for what a thing IS, never for the colour it comes out
    as. `measured` is green on a control that somebody has answered for and
    green again in the legend that explains it, and this class is the single
    place that decides so.

    `head`, `subhead` and `meta` are one ladder and are meant to be read as
    one: the section, the thing it names, and the detail under it.

    Base colours only, and never yellow. These draw on the terminal's own
    background, and this wizard runs on a light terminal as often as a dark
    one. Green, red, blue and magenta read on both; yellow on white does not.
    """

    BLUE, GREEN, RED, MAGENTA = (curses.COLOR_BLUE, curses.COLOR_GREEN,
                                 curses.COLOR_RED, curses.COLOR_MAGENTA)

    def __init__(self, colour=False):
        self.colour = colour
        self._pairs = 0
        norm, bold, dim, rev = (curses.A_NORMAL, curses.A_BOLD,
                                curses.A_DIM, curses.A_REVERSE)
        self.title = self._tone(None, bold, bold)
        self.head = self._tone(self.BLUE, bold, bold)
        self.subhead = self._tone(self.BLUE, norm, norm)
        #: somebody answered for this   ·   the shape answered   ·   nothing did
        self.measured = self._tone(self.GREEN, norm, bold)
        self.guessed = self._tone(self.MAGENTA, norm, norm)
        self.unset = self._tone(self.RED, norm, dim)
        self.note = self._tone(self.MAGENTA, norm, norm)
        self.meta = self._tone(None, dim, dim)
        self.plain = self._tone(None, norm, norm)
        self.sel = self._tone(None, rev, rev)

    def _tone(self, colour, lit, dull):
        """One tone: a colour pair where there is colour, else the fallback.

        Pairs are numbered in the order they are asked for, which is why no
        caller ever sees a pair number -- there is nothing useful to say
        about 3 that `theme.unset` does not say better.
        """
        if not self.colour:
            return dull
        if colour is None:
            return lit
        self._pairs += 1
        curses.init_pair(self._pairs, colour, -1)
        return curses.color_pair(self._pairs) | lit

    def __getitem__(self, tone):
        """A tone by its name, for a line that carries its own."""
        return getattr(self, tone)


#: The frame a panel is drawn in.
TL, TR, BL, BR, H, V = '╭', '╮', '╰', '╯', '─', '│'

#: Between two independent facts on one line: `throttle · tier 1`.
SEP = ' · '

#: How wide a dialog is. Fixed rather than fitted to its longest line: a
#: box sized to its content is a different size every time, so walking a
#: list answering questions becomes a frame that jumps about under the
#: cursor and lands somewhere new on every keystroke. Lines longer than
#: this wrap; the box does not grow to meet them.
DIALOG = 62

#: Blank columns between the border and the text, each side. One reads as
#: the text having been squeezed in: the border stops being a frame and
#: becomes an edge the words are up against.
GAP = 2

#: What a screen hands back when you step out of it backwards rather than
#: answering. Not None: that already means "cancel the whole thing", and a
#: wizard has to tell "I want the previous question" from "let me out".
BACK = object()

#: A two-level tree. `└` is the last child, `├` is every other, and that is
#: the whole rule -- no stems, because nothing here nests deeper.
BRANCH, LAST = '├', '└'


def plural(n, one, many=None):
    """`3 positions`, `1 position`.

    A parenthesised s is a form nobody speaks, and on a screen that is
    otherwise man-terse it is the loudest thing on the line.
    """
    return f'{n} {one if n == 1 else (many or one + "s")}'


def lid(width, title='', right=''):
    """The top edge: what this panel is, and what it is showing.

    Built as one string rather than drawn in pieces, so a test can read what
    reached the screen. Anything that will not fit is dropped whole: a
    border that has eaten half a title says less than a plain one.
    """
    if width <= 0:
        return ''
    if width < 4:
        return (TL + H * (width - 2) + TR) if width >= 2 else H * width
    inner = width - 2
    head = f'{H} {title} ' if title else H * 2
    if len(head) > inner:
        head = head[:inner]
    tail = f' {right} ' if right else ''
    if tail and len(head) + len(tail) + 1 > inner:
        tail = ''
    return TL + head + H * max(0, inner - len(head) - len(tail)) + tail + TR


def sill(width, keys=(), tail='', note=''):
    """The bottom edge: which keys do what, and where you are.

    `note` takes the left when there is one, and the keys give way to it. A
    status line is the one thing down here that changes and the keys are the
    one thing that never does, so it goes IN the edge rather than being
    drawn over it.

    Keys are dropped from the end when they will not fit, because the list
    is written most-needed first: nothing else is reachable without moving.
    """
    if width <= 0:
        return ''
    if width < 4:
        return (BL + H * (width - 2) + BR) if width >= 2 else H * width
    inner = width - 2
    end = f' {tail} ' if tail else ''
    if len(end) > inner:
        end = ''
    room = inner - len(end)
    if note:
        return BL + f' {note} '[:room].ljust(room, H) + end + BR
    out = ''
    for k in keys:
        piece = (SEP if out else ' ') + k
        if len(out) + len(piece) + 1 > room:
            break
        out += piece
    if out:
        out += ' '
    return BL + out + H * max(0, room - len(out)) + end + BR


def fit(width, text, lead=''):
    """`text` as lines no wider than `width`, hanging under `lead`.

    A continuation line that snaps back to column 0 stops a ledger reading
    as a ledger: the wrapped half of `+40 shape and count fit` lands under
    the number instead of beside it.
    """
    room = max(6, width - len(lead))
    bits = textwrap.wrap(text, room) if text else ['']
    return [lead + bits[0]] + [' ' * len(lead) + b for b in bits[1:]]


def box_for(body, h, w, title='', full=False):
    """(y, x, height, width) for a box holding `body` on an h x w screen.

    Sized to what it holds and no larger: a help box with three inches of
    blank border says the list is longer than it is.

    `full` takes the whole terminal instead. A notice you read wants to be
    the size of what it says; a list you WORK in wants every row it can get,
    and centring it in a margin costs two of them for nothing.
    """
    if full:
        # One column short of the screen, because the bottom-right cell of a
        # terminal cannot be written and the sill would lose its corner.
        return 0, 0, h, w - 1
    # One width, not one fitted to the longest line. Fitting is what makes
    # the frame jump about under the cursor as you answer down a list.
    bw = min(w - 2, max(len(title) + 6, DIALOG))
    bw = max(bw, 2 + 2 * GAP + 1)
    # A blank row above the sill, for the same reason there are blank
    # columns beside the text: a line pressed against the edge reads as
    # one that ran out of room rather than one that ended.
    bh = min(h - 2, len(wrapped(body, bw)) + 3)
    return (h - bh) // 2, (w - bw) // 2, bh, bw


def page_room(h, extra=0):
    """(list rows, extra rows) for an h-row screen wanting `extra` under them.

    A box costs a lid and a sill, and `box_for` caps it two rows short of the
    screen as well. Forget the second pair and you build more lines than the
    box can draw, and what falls off the bottom is the last thing added --
    the hint explaining the row you are on.

    All of the extra or none of it, because half a hint is worse than no
    hint. The list then keeps three rows whatever else has to go -- a list
    you cannot move in is worse than an explanation you cannot read -- and
    below that the screen itself is the limit, because three rows drawn into
    a two-row box is the silent overflow this exists to stop.
    """
    cap = max(1, h - 4)         # all a box on this screen can draw at all
    fits = extra if cap - extra >= 3 else 0
    return min(cap, max(3, cap - fits)), fits


def text_in(x, bw):
    """(column, width) for the text inside a box at `x` that is `bw` wide.

    Pulled out of the drawing so the gap is a rule something can check. It
    was in the one layer that touches a curses window, and a gap on the
    right and none on the left drew exactly as well as a correct one.
    """
    return x + 1 + GAP, max(1, bw - 2 - 2 * GAP)


def wrapped(body, bw):
    """`body` with anything wider than the box folded to fit inside it.

    A dialog is one width, so the text yields rather than the frame.
    """
    _at, room = text_in(0, bw)
    out = []
    for line in body:
        out += fit(room, line) if len(line) > room else [line]
    return out


def overflows(body, h, w, title='', full=False):
    """Is there more than the box can show at once?"""
    return len(body) > box_for(body, h, w, title, full)[2] - 2


def tree(rows, indent=2, lead=''):
    """`rows` as [(tone, text)] under branch glyphs, last one closed off.

    Two levels is all this draws, because two levels is all anything here
    has: a thing, and what it is made of.
    """
    out = []
    for n, (tone, text) in enumerate(rows):
        glyph = LAST if n == len(rows) - 1 else BRANCH
        out.append((tone, f'{" " * indent}{glyph} {lead}{text}'))
    return out


class Tui:
    """A screen, a theme, and the boxes drawn on them."""

    def __init__(self, scr, theme=None):
        self.scr = scr
        self.theme = theme or Theme()
        #: The last full-screen draw, put back under every dialog. Without
        #: it a dialog either leaves the edges of a wider one around it or
        #: hides what you were working on; with it, neither.
        self._back = None

    # ---- the two primitives everything else is built from ----

    def key(self, timeout=0.0):
        """'enter' / 'esc' / 'up' / 'down' / a printable char / None."""
        deadline = time.monotonic() + timeout
        while True:
            c = self.scr.getch()
            if c == -1:
                if time.monotonic() >= deadline:
                    return None
                time.sleep(0.02)
                continue
            if c in (10, 13, curses.KEY_ENTER):
                return 'enter'
            if c == 27:
                return 'esc'
            if c in (8, 127, curses.KEY_BACKSPACE):
                return 'backspace'
            if c == curses.KEY_UP:
                return 'up'
            if c == curses.KEY_DOWN:
                return 'down'
            if c == curses.KEY_LEFT:
                return 'left'
            if c == curses.KEY_RIGHT:
                return 'right'
            if 32 <= c < 127:
                return chr(c)
            # resize and anything exotic: ignored rather than guessed at

    def put(self, y, x, text, attr=curses.A_NORMAL):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h:
            try:
                self.scr.addstr(y, x, text[:max(0, w - x - 1)], attr)
            except curses.error:
                pass

    # ---- frames ----
    def box(self, title, lines, keys=(), tail='', top=0, sel=None,
            full=False, right=''):
        """Draw a framed box in the middle of the screen. Returns its page.

        `lines` is [(tone, text)], so a caller decides what each row MEANS
        and this decides what that looks like.

        The screen is cleared and the last full-screen draw put back under
        it. Left alone, a dialog over a wider one keeps that one's edges
        around it and reads as two dialogs at once; cleared outright, you
        lose sight of the list you are working down.
        """
        self.scr.erase()
        if full:
            # Not the arguments this was called with: a two-panel screen
            # is also something a dialog can open over, and that is not a
            # box and cannot be written down as one.
            self._back = partial(self._draw, title, list(lines),
                                 tuple(keys), tail, 0, None, True, right)
        elif self._back is not None:
            self._back()
            self._clear_round(title, lines, full)
        page = self._draw(title, lines, keys, tail, top, sel, full, right)
        self.scr.refresh()
        return page

    def _clear_round(self, title, lines, full):
        """Blank a column either side of where a dialog is about to go.

        The list behind it otherwise runs up to the frame and is cut
        mid-word, and half a word beside a border reads as something
        broken rather than as something behind.
        """
        h, w = self.scr.getmaxyx()
        y, x, bh, bw = box_for([t for _tone, t in lines], h, w, title, full)
        for row in range(y, y + bh):
            self.put(row, max(0, x - 1), ' ')
            self.put(row, min(w - 1, x + bw), ' ')

    def _draw(self, title, lines, keys, tail, top, sel, full, right):
        """The box itself, on whatever is already there."""
        h, w = self.scr.getmaxyx()
        y, x, bh, bw = box_for([t for _tone, t in lines], h, w, title, full)
        _at, room = text_in(x, bw)
        lines = [(tone, folded) for tone, text in lines
                 for folded in (fit(room, text) if len(text) > room
                                else [text])]
        page = bh - 2
        self.put(y, x, lid(bw, title, right), self.theme.head)
        for n in range(page):
            self.put(y + 1 + n, x, V + ' ' * (bw - 2) + V, self.theme.head)
        self.put(y + bh - 1, x, sill(bw, keys, tail), self.theme.head)
        for n, (tone, text) in enumerate(lines[top:top + page]):
            lit = (self.theme.sel if sel is not None and top + n == sel
                   else self.theme[tone])
            at, room = text_in(x, bw)
            self.put(y + 1 + n, at, text[:room], lit)
        return page

    def screen(self, title, lines, keys=(), tail='', full=False, right=''):
        """One box, taking plain strings as well as toned lines."""
        return self.box(title, _paired(lines), keys, tail, full=full,
                        right=right)

    def corner(self, title, lines):
        """A small box in the bottom-right, over whatever is already there.

        Drawn after the screen it sits on rather than instead of it: it
        answers a question about the list behind it, so hiding the list
        would be answering into an empty room.
        """
        if not lines:
            return
        h, w = self.scr.getmaxyx()
        body = [t for _tone, t in lines]
        wide = max((len(t) for t in body), default=0)
        bw = min(w - 4, max(len(title) + 6, wide + 2 + 2 * GAP))
        bh = min(h - 2, len(body) + 2)
        y, x = h - bh - 1, w - bw - 2
        # A blank column down its left, for the same reason a dialog has
        # one: the list behind runs up to the frame and is cut mid-word.
        for row in range(y, y + bh):
            self.put(row, max(0, x - 1), ' ')
        self.put(y, x, lid(bw, title), self.theme.head)
        for n in range(bh - 2):
            self.put(y + 1 + n, x, V + ' ' * (bw - 2) + V, self.theme.head)
        self.put(y + bh - 1, x, sill(bw), self.theme.head)
        at, room = text_in(x, bw)
        for n, (tone, text) in enumerate(lines[:bh - 2]):
            self.put(y + 1 + n, at, text[:room], self.theme[tone])

    def halves(self, h, w, least=34):
        """((y, x, h, w) for the list, same for the detail).

        Side by side, because the detail is about the row the cursor is
        on: putting it on a second screen means holding the row in your
        head while you read what it says.
        """
        left = max(least, (w - 1) * 3 // 5)
        return (0, 0, h, left), (0, left, h, w - 1 - left)

    def browse(self, title, lines, side, keys=(), tail='', right='',
               index=0, takes=(), aside='', poll=None, count=None):
        """A list on the left, what the cursor is on described on the right.

        Returns `(what, index)`: `what` is `\'enter\'`, one of `takes`, or
        None for ESC. Both halves, because a key that acts on the row under
        the cursor is useless without knowing which row that is.

        `side(n)` says what row `n` is, as `(title, [(tone, text)])`. Called
        while the cursor moves, so it has to be cheap.

        `poll()` is asked each tick and may return an index to jump to --
        it is how the hardware in your hands moves the cursor.

        `count(n)` is what the detail panel's edge says about row `n`. The
        default counts rows, which is right until the list has headings in
        it and the rows stop matching the things they list.
        """
        sel, top = index, 0
        while True:
            if poll is not None:
                at = poll()
                if at is not None:
                    sel = at
            h, w = self.scr.getmaxyx()
            page = self.halves(h, w)[0][2] - 2
            sel = max(0, min(sel, len(lines) - 1))
            if sel < top:
                top = sel
            elif sel >= top + page:
                top = sel - page + 1
            self.scr.erase()
            self._halves(title, lines, side, keys, tail, right, aside,
                         count, sel, top)
            # What a dialog opened from here sits on. Without this the
            # backdrop is whatever full-screen box came last, which is not
            # the screen you opened the dialog from.
            self._back = partial(self._halves, title, lines, side, keys,
                                 tail, right, aside, count, sel, top)
            self.scr.refresh()
            k = self.key(0.1 if poll is not None else 0.5)
            if k in ('up', 'k'):
                sel -= 1
            elif k in ('down', 'j'):
                sel += 1
            elif k == 'g':
                sel = 0
            elif k == 'G':
                sel = len(lines) - 1
            elif k == 'enter':
                return 'enter', sel
            elif k in takes:
                return k, sel
            elif k == 'esc':
                return None, sel

    def _halves(self, title, lines, side, keys, tail, right, aside, count,
                sel, top):
        """Both panels, on whatever is already there."""
        h, w = self.scr.getmaxyx()
        (ly, lx, lh, lw), (ry, rx, rh, rw) = self.halves(h, w)
        self._frame((ly, lx, lh, lw), title, right, keys, tail)
        at, room = text_in(lx, lw)
        for n, (tone, text) in enumerate(lines[top:top + lh - 2]):
            lit = self.theme.sel if top + n == sel else self.theme[tone]
            self.put(ly + 1 + n, at, text[:room], lit)
        head, rows = side(sel)
        self._frame((ry, rx, rh, rw), head or aside,
                    count(sel) if count is not None
                    else f'{sel + 1} of {len(lines)}')
        at, room = text_in(rx, rw)
        said = [x for tone, text in rows
                for x in ((tone, f) for f in fit(room, text))]
        for n, (tone, text) in enumerate(said[:rh - 2]):
            self.put(ry + 1 + n, at, text[:room], self.theme[tone])

    def _frame(self, rect, title, right='', keys=(), tail=''):
        """Just the border of a panel."""
        y, x, h, w = rect
        self.put(y, x, lid(w, title, right), self.theme.head)
        for row in range(y + 1, y + h - 1):
            self.put(row, x, V, self.theme.head)
            self.put(row, x + w - 1, V, self.theme.head)
        self.put(y + h - 1, x, sill(w, keys, tail), self.theme.head)

    # ---- boxes you do something with ----

    def popup(self, title, lines, full=False):
        """A box you read and dismiss. Scrolls rather than truncating.

        What falls off the bottom of a truncated help box is the
        least-used half, which is the half somebody opening the help is
        most likely to be after.
        """
        body = [t for _tone, t in lines]
        top = 0
        while True:
            h, w = self.scr.getmaxyx()
            page = box_for(body, h, w, title, full)[2] - 2
            more = overflows(body, h, w, title, full)
            top = max(0, min(top, len(body) - page)) if more else 0
            self.box(title, lines,
                     ('↑↓ more', 'any other key closes') if more else (),
                     f'{top + page} of {len(body)}' if more
                     else 'any key to close', top, full=full)
            k = self.key(0.5)
            if k is None:
                continue
            if more and k in ('up', 'k'):
                top -= 1
            elif more and k in ('down', 'j'):
                top += 1
            elif more and k == ' ':
                top += page
            else:
                return

    def choose(self, title, lines, tail='', index=0, keys=None, full=False,
               takes=(), right='', poll=None, corner=''):
        """A box you pick a line out of.

        The index picked, or None on ESC, or one of `takes` -- a key that is
        about the list rather than about a row in it. A screen that can only
        say yes or no to the thing under the cursor needs a second screen
        for everything else it can do.
        """
        sel, top = index, 0
        shown = []
        while True:
            # Asked before the frame is drawn, so what it hands back lands
            # in the same frame rather than a tick behind it.
            if poll is not None:
                said = poll()
                if said is not None:
                    at, shown = said
                    if at is not None:
                        sel = at
            h, w = self.scr.getmaxyx()
            page = box_for([t for _, t in lines], h, w, title, full)[2] - 2
            sel = max(0, min(sel, len(lines) - 1))
            if sel < top:
                top = sel
            elif sel >= top + page:
                top = sel - page + 1
            self.box(title, lines,
                     keys or ('↑↓ move', '↵ choose', 'ESC back'),
                     tail or f'{sel + 1} of {len(lines)}', top, sel, full,
                     right=right)
            self.corner(corner, shown)
            self.scr.refresh()
            k = self.key(0.1 if poll is not None else 0.5)
            if k in ('up', 'k'):
                sel -= 1
            elif k in ('down', 'j'):
                sel += 1
            elif k == 'g':
                sel = 0
            elif k == 'G':
                sel = len(lines) - 1
            elif k == 'enter':
                return sel
            elif k in takes:
                return k
            elif k == 'esc':
                return None

    def confirm(self, title, lines, aside=(), default=True):
        """Show what is about to happen and wait for an answer.

        RETURN takes the suggested one. What was missing from a typed-word
        gate was never a gate -- it was seeing what the keystroke would do
        while there was still time to say no.

        `aside` explains the choice and sits under it, separated by a blank
        row, rather than in a band pinned to the bottom of the screen: a
        band is the same height whether it has something to say or nothing.
        """
        said = list(_paired(lines)) + aside_of(aside)
        while True:
            self.box(title, said,
                     ('y yes', 'n no', 'ESC back'),
                     f'↵ = {"yes" if default else "no"}')
            k = self.key(0.5)
            if k in ('y', 'Y'):
                return True
            if k in ('n', 'N'):
                return False
            if k == 'enter':
                return default
            if k == 'esc':
                return None

    def ask(self, title, lines=(), default=''):
        """A line of text. Returns it, the default for empty, None on ESC."""
        value = ''
        while True:
            said = [('plain', t) for t in lines]
            said.append(('plain', ''))
            said.append(('sel', f'{value}_'))
            self.box(title, said, ('↵ accept', 'ESC back'),
                     f'default: {default}' if default else '')
            k = self.key(0.5)
            if k == 'enter':
                return value or default
            if k == 'esc':
                return None
            if k == 'backspace':
                value = value[:-1]
            elif k and len(k) == 1 and k.isprintable():
                value += k

    def menu(self, title, items, hints=None, subtitle='', index=0,
             multi=False, selected=None, tail='', quits=False, under=(),
             back=False):
        """Pick from a list, with the chosen item's hint under it.

        The hint sits inside the same frame rather than in a band pinned to
        the bottom of the screen. A band is the same height whether it has
        something to say or nothing, and it moves the list every time the
        terminal resizes.
        """
        ticked: set[int] = set(selected or ())
        sel, top = max(0, min(index, len(items) - 1)), 0
        keys = (('↑↓ move', 'SPACE tick', '↵ done', 'ESC back') if multi
                else ('↑↓ move', '↵ choose', 'ESC back'))
        while True:
            h, _w = self.scr.getmaxyx()
            head = [('subhead', subtitle), ('plain', '')] if subtitle else []
            want = aside_of(hints[sel] if hints and sel < len(hints) else [])
            below = ([('plain', '')] + list(under)) if under else []
            room, spare = page_room(h, len(want) + len(head) + len(below))
            foot = (want if spare else []) + (below if spare or not want
                                              else [])
            if sel < top:
                top = sel
            elif sel >= top + room:
                top = sel - room + 1
            shown = []
            for n, item in enumerate(items[top:top + room]):
                mark = ('[x] ' if top + n in ticked else '[ ] ') if multi else ''
                shown.append(('plain', f'{mark}{item}'))
            lines = head + shown + foot
            self.box(title, lines, keys + (('← back',) if back else ()),
                     tail or f'{sel + 1} of {len(items)}',
                     sel=len(head) + sel - top)
            k = self.key(0.5)
            if k in ('up', 'k'):
                sel = (sel - 1) % len(items)
            elif k in ('down', 'j'):
                sel = (sel + 1) % len(items)
            elif multi and k == ' ':
                ticked.symmetric_difference_update({sel})
            elif k == 'enter':
                return sorted(ticked) if multi else sel
            elif back and k == 'left':
                return BACK
            elif k == 'esc' or (quits and k in ('q', 'Q')):
                return None


def aside_of(lines):
    """An explanation under what it explains, after a blank row.

    A blank row between each of them as well: they are paragraphs, and two
    paragraphs run together are one paragraph that changes the subject.
    """
    said = [t for t in (lines or []) if t]
    if not said:
        return []
    out = []
    for line in said:
        out += [('plain', ''), ('meta', line)]
    return out


def _paired(lines):
    """`lines` as (tone, text), accepting a plain string as `plain`."""
    return [('plain', ln) if isinstance(ln, str) else tuple(ln)
            for ln in lines]


def setup(scr):
    """A `Tui` on a screen ready to be drawn on.

    `set_escdelay` is what makes ESC answer at once rather than after the
    terminal's own escape timeout. Colour is started so `use_default_colors`
    hands the terminal's palette back rather than painting one over it.
    """
    curses.curs_set(0)
    scr.nodelay(True)
    scr.keypad(True)
    try:
        curses.set_escdelay(50)
    except AttributeError:
        pass
    colour = False
    try:
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            colour = True
    except curses.error:
        pass
    return Tui(scr, Theme(colour))
