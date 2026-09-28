"""Walking the questions in `questions.toml`.

    sheet = read()
    run = Run(sheet)
    while (ask := run.next()):
        run.answer(ask, whatever_the_screen_got(ask))

The order and the branching used to be a 215-line function of nested
`if kind ==`, with a second copy of the same menus for editing. Here the
order is data and this walks it, so capture and edit are one path: editing
is a run that starts with answers already in it.

Answers are held by the id of the question that produced them, never by the
field they set. Several questions set `states`, and keying on the field
would mean going back to one of them wiped another's answer.

Going back keeps what still applies. Saying a control is a hat8 rather than
a hat4 should not cost you its name -- only the answers whose question no
longer applies are dropped, and `revise` returns them so the screen can say
how many went.
"""

import os
import dataclasses
import tomllib

import devicemap
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
SHEET = os.path.join(HERE, 'questions.toml')

#: What a question is asked about. See the descriptor's own header for why
#: these three and not one.
CONTROL, DEVICE, ALL = 'control', 'device', 'all'

#: Every widget a question may be drawn with. `ask_one` draws all but
#: `rounds`, which is a whole-device pass and has its own screen.
#:
#: Closed, and checked when the descriptor loads. A typo here used to
#: reach `ask_one`, which raises -- in the middle of a capture, with
#: curses up, after you had answered everything before it.
WIDGETS = ('collect', 'pick', 'tick', 'name', 'press', 'watch', 'sort',
           'slot', 'sweep', 'rounds')

#: What a vocabulary entry may say. Closed for the same reason `[[ask]]`
#: is: a dataclass refuses `notee` outright, and a plain dict took `hnit`
#: and dropped the hint off every screen that shows that choice.
#:
#:   name/value  what choosing it stores -- see `stored`
#:   says        the words for it
#:   hint        lines under it while the cursor is on it
#:   dirs        the positions it brings with it (a hat knows its own)
#:   asks_way    it points somewhere and the shape does not say where
#:   walked      false for a level that is not a round you walk
#:   axes        what each axis of the shape is called, in role order.
#:               How many there are is how long it is, the way `dirs`
#:               says how many positions a hat has.
ENTRY_KEYS = ('name', 'value', 'says', 'hint', 'dirs', 'asks_way',
              'walked', 'axes')

#: Keys a vocabulary entry carries into the answers beside its own name.
#: Picking `hat4` says the control has four positions AND what they are
#: called, and the second half is what the next question needs.
CARRIES = ('dirs', 'asks_way', 'axes')


@dataclass
class Ask:
    id: str
    of: str
    how: str                # collect pick tick name press watch sort rounds
    says: str
    sets: str = ''
    #: What a box in the trail is labelled with. The id with its
    #: underscores taken out, unless the descriptor says otherwise.
    called: str = ''
    only: str = 'always'    # a name in ONLY, never an expression
    uses: str = ''          # a vocabulary to choose from
    note: str = ''
    skip: bool = False      # RETURN is a valid answer meaning "none"


#: What a control can be asked about, straight off the class that holds
#: it. Not a list here: a second one would be a second thing to keep in
#: step with the reader.
_GROUP_FIELDS = frozenset(f.name for f in
                          dataclasses.fields(devicemap.Group))


def walkable(sheet):
    """The postures a reach round can be walked in.

    Not every level is one. OFF is where a control ends up when no round
    reached it -- there is no round to walk with your hand off the
    device, and offering one asks you to press what you cannot touch.
    """
    return [c for c in sheet.vocabulary.get('level', ())
            if c.get('walked', True)]


def stored(entry):
    """What choosing this entry writes to the file.

    A vocabulary is either a set of names -- `trigger`, `HOME` -- or a
    scale, and a scale carries `value`, a number. The number is the point:
    `low` and `high` only sort because somebody remembered which way round
    they went, and the day two places remember differently nothing says so.
    """
    return entry['value'] if 'value' in entry else entry['name']


@dataclass
class Sheet:
    asks: list = field(default_factory=list)
    vocabulary: dict = field(default_factory=dict)

    def of(self, what):
        """Every question asked about one kind of thing, in order."""
        return [a for a in self.asks if a.of == what]

    def choices(self, ask):
        """What an `uses` question offers, as [{name, says, hint, ...}]."""
        return list(self.vocabulary.get(ask.uses, ()))

    def choice(self, ask, answer):
        """One entry of that vocabulary, by what it is stored as."""
        return next((c for c in self.choices(ask) if stored(c) == answer), None)


def read(path=SHEET):
    """The descriptor, checked.

    A question whose `only` names nothing would simply never fire, and a
    question whose `uses` names nothing would offer an empty list. Both are
    silent, and a silent question is one you find out about by noticing the
    wizard never asked you something.
    """
    with open(path, 'rb') as fh:
        data = tomllib.load(fh)
    sheet = Sheet(asks=[Ask(**a) for a in data.get('ask', [])],
                  vocabulary={k: [dict(v) for v in vs]
                              for k, vs in (data.get('vocabulary')
                                            or {}).items()})
    check(sheet)
    return sheet


def check(sheet):
    """Everything the descriptor names has to exist. Raises if it does not."""
    seen = set()
    for a in sheet.asks:
        if a.id in seen:
            raise ValueError(f'two questions called {a.id!r}')
        seen.add(a.id)
        if a.of not in (CONTROL, DEVICE, ALL):
            raise ValueError(f'{a.id}: asked of {a.of!r}, which is nothing')
        if a.only not in ONLY:
            raise ValueError(f'{a.id}: only = {a.only!r} names no rule')
        if a.uses and a.uses not in sheet.vocabulary:
            raise ValueError(f'{a.id}: uses = {a.uses!r} names no vocabulary')
        if a.how not in WIDGETS:
            raise ValueError(f'{a.id}: how = {a.how!r} is no widget;'
                             f' one of {", ".join(WIDGETS)}')
        if a.how in ('pick', 'tick') and not a.uses and a.of != ALL:
            raise ValueError(f'{a.id}: {a.how} with nothing to pick from')
        # `sets` is the name an answer is filed under, and for a question
        # asked of every control it is the field itself -- `_set_fact`
        # writes it straight onto the group and into the file. A typo
        # there was found on the next load, by which time you had
        # answered thirty controls into a field nothing reads.
        if a.of == ALL and a.sets not in _GROUP_FIELDS:
            raise ValueError(f'{a.id}: sets = {a.sets!r} is no field of a'
                             ' control')
    # The names a control may carry are closed by the reader, and the
    # words for them live here. Two lists, one truth: a shape offered on
    # screen that the reader will not accept is a capture you cannot save.
    # Which shapes latch and which click are facts about shapes, and the
    # reader owns the list of shapes. The descriptor owns only the words,
    # so there is nowhere for the two to disagree.
    for table in (devicemap.LATCHING, devicemap.CLICKS):
        if set(table) - set(devicemap.SHAPES):
            raise ValueError(f'{sorted(set(table) - set(devicemap.SHAPES))}'
                             ' is not a shape')
    # The ORDER of the levels is the tier, so this is not a subset check:
    # the two tables have to be the same list in the same order, or the
    # words on screen and the distance they stand for come apart.
    said = tuple(c['name'] for c in sheet.vocabulary.get('level', ()))
    if said != devicemap.LEVELS:
        raise ValueError(f'level: {said} is not {devicemap.LEVELS}')
    # Every kind a control may be, not only the ones with buttons: the
    # walk describes an axis control too, and a menu that cannot say
    # `lever` is a control you can open and not describe.
    offered = {c['name'] for c in sheet.vocabulary.get('kind', ())}
    if offered - set(devicemap.KINDS):
        raise ValueError(f'kind: offers {sorted(offered - set(devicemap.KINDS))},'
                         ' which devicemap will not accept')
    for c in sheet.vocabulary.get('kind', ()):
        if len(c.get('axes') or []) > len(devicemap.AXIS_ROLES):
            raise ValueError(f'kind: {c["name"]!r} has'
                             f' {len(c["axes"])} axes, and there are only'
                             f' {len(devicemap.AXIS_ROLES)} ways to say'
                             ' which is which')
    for name, entries in sheet.vocabulary.items():
        for c in entries:
            odd = sorted(set(c) - set(ENTRY_KEYS))
            if odd:
                raise ValueError(f'{name}: {c.get("name", c.get("value"))!r}'
                                 f' says {odd}, which nothing reads;'
                                 f' one of {", ".join(ENTRY_KEYS)}')
            if 'says' not in c:
                raise ValueError(f'{name}: an entry with no words for it: {c}')
            if ('name' in c) == ('value' in c):
                raise ValueError(f'{name}: an entry is stored as its name or'
                                 f' as its value, never both or neither: {c}')
            if 'value' in c and not isinstance(c['value'], int):
                raise ValueError(f'{name}: value = {c["value"]!r} is not a'
                                 ' number, so it does not sort')
    return sheet


#: Whether a question applies, given what has been answered so far.
#:
#: Named rather than written as text in the descriptor, so a typo is an
#: error at load rather than a question that silently never fires.
#:
#: These read `kind`, which is a word -- but it is a word the person just
#: chose, not one parsed out of a capture file. "You said it is a trigger,
#: so let me watch you pull it" is a different thing from deciding what a
#: control is good for by matching strings.
ONLY = {
    'always': lambda said: True,
    'can_click': lambda said: said.get('kind') in devicemap.CLICKS,
    'is_trigger': lambda said: said.get('kind') == 'trigger',
    'is_selector': lambda said: said.get('kind') == 'selector',
    # NOT `and not said.get('dirs')`. That reads as "we have not been told
    # yet", and the answer is what tells us -- so answering falsified the
    # rule that asked, and `settle` threw the answer away again.
    'asks_which_way': lambda said: bool(said.get('asks_way')),
    'has_directions': lambda said: len(said.get('dirs') or ()) > 1,
    # The shape says how many axes it has and what each is called, so a
    # control that owns any is one the walk has to ask about.
    'owns_axes': lambda said: bool(said.get('axes')),
    'found_rest_contact': lambda said: (said.get('pull')
                                        or {}).get('rest') is not None,
    # Only something that STAYS where you put it can have a place the game
    # never hears about. A sprung control is either sending or at rest.
    'may_sit_silent': lambda said: said.get('kind') in devicemap.LATCHING,
}


def answered(ask, got):
    """Whether what a screen came back with counts as an answer.

    `skip` marks the questions where nothing IS the answer -- a control
    that does not click has to be able to say so, and so does a stick,
    which is three axes and not one button.

    Nothing pressed used to be refused here, to stop a control with no
    buttons reaching the list as a row with no name and no way to give
    it one. That guard now sits where it belongs: `_replace` refuses an
    entry that owns neither a button nor an axis, which is the thing
    that was actually wrong with it.
    """
    if got is None:
        return bool(ask.skip)
    if ask.how == 'collect' and not ask.skip:
        seen, _held = got
        return bool(seen)
    return True


class Run:
    """One pass of the questions over one thing.

    `given` maps a question's id to the answer it got; everything else is
    worked out from that, so there is one place a fact can come from.
    """

    def __init__(self, sheet, of=CONTROL, given=None):
        self.sheet = sheet
        self.of = of
        self.given = dict(given or {})
        self.order = [a.id for a in sheet.of(of) if a.id in self.given]
        # A control captured as a hat and since changed to a button still
        # has the hat's answers in the file. They are not this control's
        # answers any more, and a trail that shows them says so falsely.
        self.settle()

    @property
    def by_id(self):
        return {a.id: a for a in self.sheet.of(self.of)}

    @property
    def said(self):
        """What the answers amount to, for a predicate to read.

        Keyed by the id of the question that gave each answer, plus whatever
        the chosen vocabulary entry carried. Not by `sets`: `sweep`, `pull`
        and `order` all set `states` and all hand back a different shape, so
        a predicate reading `states` would be reading whichever of them
        happened to run.
        """
        out = {}
        for aid in self.order:
            ask = self.by_id[aid]
            value = self.given[aid]
            out[aid] = value
            entry = (self.sheet.choice(ask, value)
                     if ask.uses and isinstance(value, str) else None)
            for k in CARRIES:
                if entry and entry.get(k):
                    out[k] = entry[k]
        return out

    def wanted(self):
        """Every question that applies, given what has been said."""
        return [a for a in self.sheet.of(self.of) if ONLY[a.only](self.said)]

    def next(self):
        """The next question with no answer yet, or None when done."""
        return next((a for a in self.wanted() if a.id not in self.order), None)

    def answer(self, ask, value):
        """Record an answer and move on."""
        self.given[ask.id] = value
        if ask.id not in self.order:
            self.order.append(ask.id)
        return self

    def revise(self, ask, value):
        """Change an answer already given. Returns the ids it invalidated.

        Only the questions that no longer apply are dropped. Everything
        still applicable keeps its answer, including questions asked after
        this one -- the name you gave a control does not stop being its name
        because you corrected its shape.
        """
        self.answer(ask, value)
        return self.settle()

    def settle(self):
        """Drop every answer whose question no longer applies. Returns them.

        Iterated, because dropping one answer changes what applies: a
        control that stops being a two-way hat loses the answer that said
        which two ways, and that answer was what made the ordering question
        apply at all.
        """
        gone = []
        while True:
            keep = {a.id for a in self.wanted()}
            went = [i for i in self.order if i not in keep]
            if not went:
                return gone
            for i in went:
                self.order.remove(i)
                self.given.pop(i, None)
            gone += went

    def trail(self):
        """[(Ask, shown)] for the answers so far, in the order given.

        This is what the boxes under the question show, and what stepping
        back walks: each one is a question you can return to.
        """
        out = []
        for aid in self.order:
            ask = self.by_id[aid]
            value = self.given[aid]
            entry = (self.sheet.choice(ask, value)
                     if ask.uses and isinstance(value, str) else None)
            out.append((ask, entry['says'] if entry else _shown(value)))
        return out

    @property
    def done(self):
        return self.next() is None

    def left(self):
        """How many questions are still to answer."""
        return len([a for a in self.wanted() if a.id not in self.order])


def _shown(value):
    """An answer as a line of text."""
    if value is None:
        return '--'
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    # What `collect` hands back: the buttons pressed, and which of them were
    # still down at the end. The second half is a fact about the control --
    # it is what tells a switch that stays put from a sprung one -- but it
    # is not what the box is for.
    if (isinstance(value, tuple) and len(value) == 2
            and isinstance(value[1], (set, frozenset))):
        seen, held = value
        return (', '.join(str(b) for b in seen) or '--') + (
            f'  ({len(held)} held)' if held else '')
    if isinstance(value, (list, tuple)):
        return ', '.join(str(v) for v in value) or '--'
    if isinstance(value, dict):
        return ', '.join(f'{k} {v}' for k, v in value.items()) or '--'
    return str(value)
