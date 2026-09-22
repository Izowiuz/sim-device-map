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
import tomllib
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
SHEET = os.path.join(HERE, 'questions.toml')

#: What a question is asked about. See the descriptor's own header for why
#: these three and not one.
CONTROL, DEVICE, ALL = 'control', 'device', 'all'

#: Shapes that press in as well as doing whatever else they do.
CLICKS = ('hat2', 'hat4', 'hat8', 'encoder', 'ministick', 'dial')

#: Keys a vocabulary entry carries into the answers beside its own name.
#: Picking `hat4` says the control has four positions AND what they are
#: called, and the second half is what the next question needs.
CARRIES = ('dirs', 'asks_way')


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

    def choice(self, ask, name):
        """One entry of that vocabulary, by name."""
        return next((c for c in self.choices(ask) if c['name'] == name), None)


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
        if a.how in ('pick', 'tick') and not a.uses and a.of != ALL:
            raise ValueError(f'{a.id}: {a.how} with nothing to pick from')
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
    'can_click': lambda said: said.get('kind') in CLICKS,
    'is_trigger': lambda said: said.get('kind') == 'trigger',
    'is_selector': lambda said: said.get('kind') == 'selector',
    # NOT `and not said.get('dirs')`. That reads as "we have not been told
    # yet", and the answer is what tells us -- so answering falsified the
    # rule that asked, and `settle` threw the answer away again.
    'asks_which_way': lambda said: bool(said.get('asks_way')),
    'has_directions': lambda said: len(said.get('dirs') or ()) > 1,
    'found_rest_contact': lambda said: (said.get('pull')
                                        or {}).get('rest') is not None,
}


def answered(ask, got):
    """Whether what a screen came back with counts as an answer.

    RETURN with nothing pressed is not one. Taken as one it says the
    control has no buttons, and a control with no buttons is a row in the
    list with no name and no way ever to give it one.

    `skip` marks the questions where nothing IS the answer -- a control
    that does not click has to be able to say so.
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
