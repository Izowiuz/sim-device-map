"""What the wizard's screens say, worked out before anything is drawn.

Everything here returns `[(tone, text)]` or a plain list, and nothing here
touches a curses window. That is what makes it testable: a screen built as
strings can be read back, and the last two attempts at chrome in this family
passed every test while drawing one thing over another.

The flows that put these on a screen live in `capture.py`. This is the half
that has something to get wrong.
"""

from dataclasses import dataclass

import devicemap
import tui as ui

#: Marks against a control in the list, and the tone each one asks for.
#: The three states are the only thing the list is really for: what is
#: answered, what is standing in for an answer, and what is not there yet.
MARK = {'measured': '+', 'guessed': '?', 'missing': ' '}
TONE = {'measured': 'measured', 'guessed': 'guessed', 'missing': 'unset'}

#: The ergonomic facts, in the order the list shows them.
FACTS = ('hold_ok', 'rapid_ok', 'modifier_ok', 'blind_distinct',
         'accident_risk')


#: What the control list can do. One list, so the border and the help
#: cannot disagree about which keys there are: the sill is built from the
#: second column and the help from the third.
KEYS = (
    ('\u21b5', 'describe', 'describe the control under the cursor'),
    ('n', 'new', 'press a control that is not in the file yet'),
    ('r', 'reach', 'work out how far each control is, by reaching'),
    ('f', 'facts', 'answer one question about how each control feels'),
    ('a', 'an axis', 'describe an axis'),
    ('u', 'unwired', 'say the leftover buttons have nothing behind them'),
    ('s', 'save', 'write the device file'),
    ('?', 'help', 'these keys'),
    ('q', 'quit', 'back to the device list'),
)


def sill_keys():
    """The key names for the border, most-needed first."""
    return tuple(f'{k} {says}' for k, says, _what in KEYS
                 if k not in ('?', 'q')) + ('q quit',)


def takes():
    """Every key the list answers to, either case."""
    out = []
    for k, _says, _what in KEYS:
        if k.isalpha():
            out += [k, k.upper()]
        elif k != '\u21b5':
            out.append(k)
    return tuple(out)


def key_help():
    """The keys, as a man page: what each does and nothing about why."""
    out = [('head', 'NAME'),
           ('plain', '  the control list \u2014 describe one device'),
           ('plain', ''),
           ('head', 'KEYS')]
    wide = max(len(k) for k, _s, _w in KEYS)
    for k, _says, what in KEYS:
        out.append(('plain', f'  {k:<{wide}}  {what}'))
    out += [('plain', ''),
            ('head', 'ROWS THAT ARE NOT CONTROLS')]
    wide = max(len(said) for said, _why in NOT_A_CONTROL.values())
    for said, why in NOT_A_CONTROL.values():
        out.append(('plain', f'  {said:<{wide}}  {why}'))
    out += [('plain', ''),
            ('head', 'MARKS'),
            ('plain', f'  {MARK["measured"]}  fully described'),
            ('plain', f'  {MARK["guessed"]}  not fully described'),
            ('plain', f'  {MARK["missing"].strip() or chr(0x2423)}'
                      '  nothing recorded at all'),
            ('plain', ''),
            ('meta', '  the end of each line says what is still wanted')]
    return out


def note_lines(ask):
    """A question's note as paragraphs, not as the lines the file has.

    A note in the descriptor is wrapped wherever the TOML happened to end
    a line, and honouring those breaks folds every one of them twice --
    once at the file's width and again at the box's. The box wraps; this
    only says where a paragraph ends.
    """
    out = []
    for para in (ask.note or '').split('\n\n'):
        said = ' '.join(para.split())
        if said:
            out.append(said)
    return out


def caption(ask):
    """What a box in the trail is labelled with."""
    return ask.called or ask.id.replace('_', ' ')


def trail_tree(trail, width, lead='answered so far'):
    """The answers so far, as a tree under the question.

    A row of boxes was the first shape this took and it was the wrong one.
    An answer is a name and a value, which reads down a column; a box each
    pays three lines and a sixteen-character cap for a shape that goes
    sideways, and by the fifth answer most of them are off the edge.
    """
    if not trail:
        return []
    wide = max(len(caption(a)) for a, _shown in trail)
    room = max(8, width - wide - 8)
    rows = []
    for ask, shown in trail:
        said = shown if len(shown) <= room else shown[:room - 1] + '\u2026'
        rows.append(('meta', f'{caption(ask):<{wide}}   {said}'))
    # Indented under the line that names it, and not at all without
    # one: a branch hanging off nothing is a branch off the frame.
    return (([('plain', ''), ('meta', lead)] if lead else [])
            + ui.tree(rows, indent=2 if lead else 0))


@dataclass
class Row:
    """One line of the control list, and what it stands for."""
    tone: str
    text: str
    group: object = None        # the control, where the row is one
    button: int | None = None   # the button, where it is not described yet


def control_rows(dev):
    """[Row] -- every control, and every button that is not one yet.

    The buttons nobody has described used to be a single row, and that row
    did nothing: the most natural gesture on this screen -- put the cursor
    on what is missing and press RETURN -- was the one that was dead.

    One row each, then. Until you press them there is no knowing that four
    of them are one hat, and saying so is more honest than a pile.
    """
    out = []
    for g in dev.groups():
        if g.kind == 'unknown':
            out += [_loose_row(b) for b in sorted(g.all_buttons)]
            continue
        state = _state(g)
        out.append(Row(TONE[state],
                       f'{MARK[state]} {_called(g)[:28]:28} '
                       f'{_owns(g):14} {_where(g):9} {_left_said(g)}',
                       group=g))
    return out


#: What a finger is called in a sentence. `middle` alone reads as the
#: middle of something.
FINGER_SAID = {'thumb': 'thumb', 'index': 'index finger',
               'middle': 'middle finger', 'ring': 'ring finger',
               'pinky': 'pinky'}


def finger_said(name):
    return FINGER_SAID.get(name, name)


@dataclass
class Round:
    """One pass of the reach measurement: a posture and a finger."""
    level: dict
    finger: str
    found: list                 # control ids this round reached
    done: bool                  # whether it has been walked at all


def reach_rounds(dev, prof, levels):
    """[Round] -- every posture and finger, and what each has found.

    Fifteen of them for a whole device, not fifteen per control: in one
    round you press everything that one finger reaches from one posture,
    which on a throttle is usually a handful of controls and often none.
    """
    said = (prof.entry(dev.slug) or {}).get('access') or {}
    walked = (prof.entry(dev.slug) or {}).get('rounds') or []
    out = []
    for lvl in levels:
        for finger in devicemap.FINGERS:
            found = [c for c, spots in said.items()
                     if any(sp.get('level') == lvl['name']
                            and sp.get('finger') == finger for sp in spots)]
            out.append(Round(lvl, finger, sorted(found),
                             [lvl['name'], finger] in walked or bool(found)))
    return out


def reach_rows(rounds):
    """[(tone, text)] -- the rounds as a tree of postures and fingers."""
    out, seen = [], None
    for r in rounds:
        if r.level['name'] != seen:
            seen = r.level['name']
            out.append(('subhead', r.level['says']))
        mark = MARK['measured'] if r.found else (
            MARK['guessed'] if r.done else MARK['missing'])
        said = (ui.plural(len(r.found), 'control') if r.found
                else 'nothing' if r.done else 'not done')
        out.append((TONE['measured'] if r.found else
                    TONE['guessed'] if r.done else TONE['missing'],
                    f'  {mark} {r.finger:<8} {said}'))
    return out


def reach_side(dev, rounds, at, note):
    """(title, [(tone, text)]) for the row the cursor is on.

    A posture heading gets the explanation of the whole thing; a round
    gets what it found and what pressing RETURN will do. Neither repeats
    the other, because on this screen you read one of them at a time.
    """
    one = _round_at(rounds, at)
    if one is None:
        said = [x for n, t in enumerate(note)
                for x in ((('plain', ''),) if n else ()) + (('plain', t),)]
        said += [('plain', ''),
                 ('meta', f'There are {len(rounds)} rounds for the whole'
                          ' device, not one per control. In each round you'
                          ' press whatever that one finger can reach, which'
                          ' is often nothing.')]
        return 'what the rounds are for', said

    named = {g.id: g.label or g.kind for g in dev.groups(bindable=True)}
    said = [('meta', t) for t in (one.level.get('hint') or [])]
    said.append(('plain', ''))
    if one.found:
        said.append(('measured', 'Reached this way:'))
        said += [('plain', f'  {named.get(c, c)}') for c in one.found]
        said += [('plain', ''),
                 ('meta', '\u21b5 does this round again.')]
    else:
        said.append(('guessed' if one.done else 'unset',
                     'You reached nothing this way.' if one.done
                     else 'Not done yet.'))
        said += [('plain', ''),
                 ('meta', '\u21b5 starts this round.')]
    return f'{finger_said(one.finger)}, {one.level["says"]}', said


def round_prompt(one):
    """(title, [help line], says) -- the words on one round's screen.

    Not the note that says what the rounds are for: you read that on the
    list you came from, and here it would push the posture -- the one
    thing you need right now -- off the screen.
    """
    who = f'{finger_said(one.finger)}, {one.level["says"]}'
    return (f'Reach: {who}',
            list(one.level.get('hint') or [])
            # A round that reaches nothing is an answer, and without this
            # it looks like a screen you can only leave by cancelling.
            + ['If it reaches nothing, just press RETURN.'],
            f'Press everything the {finger_said(one.finger)} can reach,'
            ' then RETURN.')


def _round_at(rows_rounds, at):
    """The round a row index stands for, or None for a posture heading."""
    n, seen = 0, None
    for r in rows_rounds:
        if r.level['name'] != seen:
            seen = r.level['name']
            if n == at:
                return None
            n += 1
        if n == at:
            return r
        n += 1
    return None


def fact_rows(dev, asks):
    """[(tone, text)] -- the five facts, and how many controls still guess.

    Per question, not per control: each of these covers every control at
    once, because "more distinct than that one" only means something side
    by side. Per control it would be five questions twenty-six times.
    """
    out = []
    wide = max((len(caption(a)) for a in asks), default=0)
    for ask in asks:
        left = _still_guessed(dev, ask)
        state = 'measured' if not left else 'guessed'
        out.append((TONE[state],
                    f'{MARK[state]} {caption(ask):<{wide}}  '
                    + (f'{left} with no answer' if left
                       else 'all answered')))
    return out


#: What a yes and a no look like against a control.
SAID = {True: '\u2713', False: '\u00b7'}


def answer_rows(dev, ask, controls):
    """[(tone, text)] -- every control and its answer to one fact."""
    out = []
    for g in controls:
        got = g.fact(ask.sets)
        told = g.told(ask.sets)
        mark = SAID[got] if isinstance(got, bool) else str(got)
        out.append((TONE[told] if told == 'measured' else 'meta',
                    f'{mark:<6} {(g.label or g.kind)[:30]:30} tier '
                    f'{g.tier if g.tier is not None else "?"}'))
    return out


def answer_side(dev, ask, controls, at):
    """(title, [(tone, text)]) for the control the cursor is on.

    Two things and nothing else: what this control answers, and the
    sentences that help you answer it. How many positions it has and how
    far away it is are true and beside the point -- the question is about
    the feel of the thing under your finger.

    Nothing here says to press it, either. The border already does, and a
    hint repeated in both places costs two rows of the note, which is the
    half that tells you how to answer.
    """
    g = controls[at]
    told = g.told(ask.sets)
    said = [(TONE[told], _answer_said(g.fact(ask.sets))
             + ('' if told == 'measured' else '   (a guess)')),
            ('plain', ''),
            ('plain', ask.says)]
    said += ui.aside_of(note_lines(ask))
    return g.label or g.kind, said


def _answer_said(got):
    """An answer in words rather than as whatever it is stored as."""
    if isinstance(got, bool):
        return 'yes' if got else 'no'
    return str(got)


def fact_side(dev, asks, at):
    """(title, [(tone, text)]) for the fact the cursor is on."""
    ask = asks[at]
    left = _still_guessed(dev, ask)
    said = [('plain', ask.says)] + ui.aside_of(note_lines(ask))
    said.append(('plain', ''))
    if left:
        said.append(('guessed', f'{ui.plural(left, "control")} have no'
                                ' answer yet.'))
    else:
        said.append(('measured', 'Every control has an answer.'))
    said += [('plain', ''),
             ('meta', '\u21b5 asks this about every control.')]
    return caption(ask), said


def _still_guessed(dev, ask):
    """How many controls have no answer to this one."""
    return sum(1 for g in dev.groups(bindable=True)
               if g.told(ask.sets) == 'guessed')


def what_is(dev, button):
    """[(tone, text)] naming one button, for the corner of the list.

    A number is not an answer to "which one did I just press": it is the
    same question again. This says what the control is called and which
    part of it the button is.
    """
    g = dev.group_of(button)
    if g is None:
        return [('unset', f'js {button}'),
                ('meta', NOT_A_CONTROL['unknown'][0])]
    if not g.bindable:
        return [('unset', f'js {button}'),
                ('meta', NOT_A_CONTROL.get(g.kind, (g.kind,))[0])]
    said = [(TONE[_state(g)], f'js {button}'),
            ('plain', _called(g))]
    way = g.direction(button)
    if way:
        said.append(('meta', way))
    if g.tier is not None:
        said.append(('meta', f'tier {g.tier}'))
    return said


def row_of(rows, dev, button):
    """Which row a pressed button belongs to, or None."""
    g = dev.group_of(button)
    for n, r in enumerate(rows):
        if r.button == button or (g is not None and r.group is g):
            return n
    return None


def _loose_row(button):
    """A button nobody has described, on a line of its own."""
    return Row(TONE['missing'],
               f'{MARK["missing"]} {"js " + str(button):28} '
               f'{"":14} {"":9} {NOT_A_CONTROL["unknown"][0]}',
               button=button)


#: The rows that are not controls at all, and what each one is. Why it is
#: that way belongs in the help, not on every line of the list.
NOT_A_CONTROL = {
    'unknown': ('not described yet', 'nobody has pressed them yet'),
    'unwired': ('nothing behind them',
                'the firmware reports them; no button is wired'),
    'switch-position': ('held at rest',
                        'closed all the time, so never offered'),
}


def _called(group):
    """What goes in the name column.

    A control nobody has named shows the buttons it sits on instead,
    because `button` where a name should be reads as a control somebody
    called `button` -- and the row then looks finished.
    """
    if not group.bindable:
        return NOT_A_CONTROL.get(group.kind, (group.kind,))[0]
    if group.label:
        return group.label
    owned = group.all_buttons
    return f'{group.kind} on js {owned[0]}' if owned else group.kind


def _owns(group):
    """How much of it there is: positions for a control, buttons for a pile.

    A row that is not a control has no positions. Calling its buttons
    positions reads as a described control with three of them, which is
    the one thing it is not.
    """
    if not group.bindable:
        return ui.plural(len(group.all_buttons), 'button')
    return ui.plural(len(group.places), 'position')


def _where(group):
    """How far it is, and nothing for a row that is not a control: reach
    is a fact about something you can put an action on."""
    if not group.bindable:
        return ''
    return f'tier {group.tier}' if group.tier is not None else 'no reach'


def _left_said(group):
    """What this row is still short of, named rather than counted."""
    if not group.bindable:
        owned = group.all_buttons
        return 'js ' + ', '.join(str(b) for b in owned) if owned else ''
    # Not "a reach": the column beside this one already says `no reach`,
    # and a row that says the same thing twice is a row with a column
    # missing rather than one with something extra.
    want = []
    if not group.label:
        want.append('a name')
    left = _unanswered(group)
    if left:
        want.append(ui.plural(left, 'fact'))
    return ', '.join(want) + (' to go' if want else '')


def _state(group):
    """One word for how far a control has got."""
    if not group.bindable:
        return 'missing'
    if not group.access or not group.label:
        return 'missing'
    if _unanswered(group):
        return 'guessed'
    return 'measured'


def _unanswered(group):
    """How many of its ergonomic facts are still the shape's guess."""
    if not group.bindable:
        return 0
    return sum(1 for f in FACTS if group.told(f) == 'guessed')


def device_rows(prof, devices):
    """[(tone, text, device)] -- the devices this rig has, and their state."""
    out = []
    for dev in devices:
        left = sum(_unanswered(g) for g in dev.groups(bindable=True))
        blank = sum(1 for g in dev.groups(bindable=True) if not g.access)
        tone = 'measured' if not left and not blank else 'guessed'
        out.append((tone,
                    f'{dev.product[:34]:34} {dev.role:9} {dev.hand or "?":6} '
                    + (f'{blank} unreached, ' if blank else '')
                    + (ui.plural(left, 'fact') + ' to go' if left
                       else 'nothing outstanding'),
                    dev))
    return out


def profile_rows(profiles, here=None):
    """[(tone, text, profile)] -- the rigs on file."""
    out = []
    for p in profiles:
        tone = 'measured' if p is here else 'plain'
        out.append((tone,
                    f'{p.name[:24]:24} {ui.plural(len(p.devices), "device")}',
                    p))
    return out


def dropped_said(gone):
    """What to say when going back has invalidated later answers."""
    if not gone:
        return ''
    return f'{ui.plural(len(gone), "answer")} no longer applies: ' \
           + ', '.join(gone)
