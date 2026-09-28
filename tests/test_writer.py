"""What reaches the file.

The writer builds TOML as text rather than through a library, so every rule it
keeps is a rule some line of `emit_str`/`emit_list` keeps by hand: quoting,
escaping, the comment banners, the column the `=` signs line up in, and the
order groups come out in. None of that is checked by parsing the result -- a
file can parse and still have lost a field.

It validates by reading the temporary file back before replacing the real one,
which is the one guarantee worth more than all the others: a crash halfway
through leaves the previous capture intact.
"""

import os
import tomllib
import unittest

import capture
import devicemap
import fake


def written(data, name='fake-device.toml'):
    """`(parsed-back TOML, raw text)` after one trip through the writer."""
    dev, box = fake.on_disk(data, name)
    try:
        capture.write_device(dev)
        with open(dev.path, 'rb') as fh:
            text = fh.read()
        return tomllib.loads(text.decode()), text.decode()
    finally:
        box.cleanup()


class ARoundTrip(unittest.TestCase):
    def test_a_group_comes_back_whole(self):
        data = fake.raw(groups=[
            fake.group('hat4', [4, 5, 6, 7], push=3,
                       dirs=['up', 'right', 'down', 'left'],
                       label='Middle finger hat'),
        ])
        back, _ = written(data)
        g = devicemap.Group(**back['group'][0])
        self.assertEqual('hat4', g.kind)
        self.assertEqual([4, 5, 6, 7], g.buttons)
        self.assertEqual(3, g.push)
        self.assertEqual(['up', 'right', 'down', 'left'], g.dirs)
        self.assertEqual('Middle finger hat', g.label)

    def test_every_contact_field_survives(self):
        # These are the fields a control owns without them being positions,
        # and the writer emits each through its own branch.
        data = fake.raw(groups=[
            fake.group('trigger', [2, 3], stages=['first', 'second'],
                       cumulative=True, rest_contact=1, travel_contact=8,
                       transient=[9]),
        ])
        back, _ = written(data)
        g = devicemap.Group(**back['group'][0])
        self.assertEqual(1, g.contact('rest'))
        self.assertEqual(8, g.contact('travel'))
        self.assertEqual([9], g.transient)
        self.assertTrue(g.cumulative)
        # A contact is not a place you can put the control, so it is not
        # one of its positions however it is stored.
        self.assertEqual([2, 3], g.buttons)

    def test_an_axis_comes_back_whole(self):
        data = fake.raw(axes=[fake.axis(3, evdev='ABS_RX', hid='Rx',
                                        rest='mid', stepped=False, role='x',
                                        range=65534, noise=3,
                                        moves_with=[4],
                                        coupling='switchable')])
        back, _ = written(data)
        a = back['axis'][0]
        self.assertEqual(3, a['index'])
        self.assertEqual('Rx', a['hid'])
        self.assertEqual('x', a['role'])
        # What it IS and what it is called are the control's to say.
        self.assertNotIn('kind', a)
        self.assertNotIn('label', a)
        self.assertIs(False, a['stepped'])
        self.assertEqual(65534, a['range'])
        self.assertEqual(3, a['noise'])

    def test_the_writer_never_puts_a_name_on_an_axis(self):
        # Poked in behind the reader's back, because the reader refuses
        # it: this pins the writer's own list of what an axis may carry,
        # which is the other half of the file holding one answer.
        dev, box = fake.on_disk(fake.raw(axes=[fake.axis(0)]))
        try:
            dev._raw['axis'][0].update({'kind': 'dial', 'label': 'Wheel'})
            capture.write_device(dev)
            with open(dev.path, 'rb') as fh:
                back = tomllib.load(fh)
        finally:
            box.cleanup()
        self.assertNotIn('kind', back['axis'][0])
        self.assertNotIn('label', back['axis'][0])

    def test_a_measurement_of_zero_is_still_a_measurement(self):
        # An axis that does not wander at all is the best kind, and
        # `if a.get(k)` would drop exactly that one back to unmeasured.
        data = fake.raw(axes=[fake.axis(0, noise=0, stepped=False)])
        back, _ = written(data)
        self.assertEqual(0, back['axis'][0]['noise'])
        self.assertIs(False, back['axis'][0]['stepped'])

    def test_an_axis_nobody_swept_says_nothing_about_sweeping(self):
        data = fake.raw(axes=[fake.axis(0)])
        _back, text = written(data)
        self.assertNotIn('stepped', text)
        self.assertNotIn('noise', text)

    def test_twice_through_changes_nothing(self):
        data = fake.raw(groups=[fake.group('button', [0], label='Pinky'),
                                fake.group('hat4', [1, 2, 3, 4], push=5)],
                        axes=[fake.axis(0)])
        once, text_once = written(data)
        twice, text_twice = written(once)
        self.assertEqual(text_once, text_twice)


class ThingsThatBreakHandBuiltToml(unittest.TestCase):
    def test_a_quote_in_a_label(self):
        back, _ = written(fake.raw(groups=[
            fake.group('button', [0], label='The "panic" button')]))
        self.assertEqual('The "panic" button', back['group'][0]['label'])

    def test_a_backslash_in_a_label(self):
        back, _ = written(fake.raw(groups=[
            fake.group('button', [0], label=r'up\down')]))
        self.assertEqual(r'up\down', back['group'][0]['label'])

    def test_a_note_long_enough_to_go_multiline(self):
        # Past 86 characters the writer switches to a triple-quoted block,
        # which is a different escaping regime, not just a longer line.
        long = ('MEASURED with probe.py: 52 consecutive pairs, identical '
                'values, 0.00s apart every time, so the catch is engaged.')
        back, text = written(fake.raw(groups=[
            fake.group('button', [0], note=long)]))
        self.assertEqual(long, back['group'][0]['note'])
        self.assertIn('"""', text)

    def test_a_note_that_already_contains_a_triple_quote(self):
        back, _ = written(fake.raw(groups=[
            fake.group('button', [0],
                       note='x' * 90 + ' and then """ happened')]))
        self.assertIn('"""', back['group'][0]['note'])

    def test_a_newline_in_a_note(self):
        back, _ = written(fake.raw(groups=[
            fake.group('button', [0], note='first line\nsecond line')]))
        self.assertEqual('first line\nsecond line',
                         back['group'][0]['note'])


class TheShapeOfTheFile(unittest.TestCase):
    def test_the_comment_block_at_the_top_is_kept(self):
        # Everything before `[device]` is prose somebody wrote about this
        # piece of hardware, and no capture ever regenerates it.
        dev, box = fake.on_disk(fake.raw(groups=[fake.group('button', [0])]))
        try:
            with open(dev.path, 'w') as fh:
                fh.write('# The left throttle.\n#\n# Axis facts are measured.\n')
            capture.write_device(dev)
            text = open(dev.path).read()
        finally:
            box.cleanup()
        self.assertTrue(text.startswith('# The left throttle.'))
        self.assertIn('# Axis facts are measured.', text)

    def test_the_uncaptured_bucket_sorts_last(self):
        data = fake.raw(groups=[fake.bucket([9], label='Not yet'),
                                fake.group('button', [0])], buttons=10)
        back, _ = written(data)
        last = back['group'][-1]
        self.assertEqual('uncaptured', last['status'])
        # One or the other. A row that is not a control has no shape, and
        # the word used to sit in `kind` where nothing could check it.
        self.assertNotIn('kind', last)

    def test_groups_sort_by_their_lowest_button(self):
        data = fake.raw(groups=[fake.group('button', [7]),
                                fake.group('button', [2]),
                                fake.group('hat4', [3, 4, 5, 6])])
        back, _ = written(data)
        self.assertEqual([[2], [3, 4, 5, 6], [7]],
                         [devicemap.Group(**g).buttons
                          for g in back['group']])

    def test_the_identity_warning_rides_along(self):
        # The evdev name carries a firmware build date, so matching on it
        # loses the device after an update. The comment is the only place
        # that says so.
        _back, text = written(fake.raw())
        self.assertIn('do not match on it', text)


class WhenItGoesWrong(unittest.TestCase):
    def test_nothing_is_left_behind_on_success(self):
        dev, box = fake.on_disk(fake.raw(groups=[fake.group('button', [0])]))
        try:
            capture.write_device(dev)
            left = os.listdir(os.path.dirname(dev.path))
        finally:
            box.cleanup()
        self.assertEqual([], [f for f in left if f.endswith('.tmp')])

    def test_the_old_file_survives_a_refusal(self):
        # An unserialisable value gets as far as the temporary file and no
        # further; what was already captured is still on disk.
        data = fake.raw(groups=[fake.group('button', [0], label='Pinky')])
        dev, box = fake.on_disk(data)
        try:
            capture.write_device(dev)
            good = open(dev.path).read()
            dev._raw['group'][0]['label'] = object()
            with self.assertRaises(Exception):
                capture.write_device(dev)
            self.assertEqual(good, open(dev.path).read())
        finally:
            box.cleanup()


if __name__ == '__main__':
    unittest.main()


class AGradedFactIsANumber(unittest.TestCase):
    """`blind_distinct` and `accident_risk` are scales, so they go in the
    file as the number that orders them, never as the word for it. The
    words live in the vocabulary and can be reworded; a file full of
    `high` and `low` only sorts because two places remember which way
    round they went."""

    SCALES = ('blind_distinct', 'accident_risk')

    def round_trip(self, field, value):
        data = fake.raw(groups=[fake.group('button', [0], label='One',
                                           **{field: value})])
        back, text = written(data)
        return devicemap.Group(**back['group'][0]), text

    def test_every_answer_survives_including_the_lowest(self):
        # Nothing here is a truth test: a control answered `no` is
        # answered, and `if g.get(k)` would drop it on the way out.
        for field in self.SCALES:
            for value in (0, 1, 2):
                with self.subTest(field=field, value=value):
                    g, _ = self.round_trip(field, value)
                    self.assertEqual(value, getattr(g, field))

    def test_the_lowest_answer_is_an_answer_and_not_a_silence(self):
        for field in self.SCALES:
            with self.subTest(field=field):
                g, _ = self.round_trip(field, 0)
                self.assertEqual('measured', g.told(field))
                self.assertEqual(0, g.fact(field))

    def test_an_unanswered_one_is_not_written_at_all(self):
        data = fake.raw(groups=[fake.group('button', [0], label='One')])
        _back, text = written(data)
        for field in self.SCALES:
            with self.subTest(field=field):
                self.assertNotIn(field, text)

    def test_it_is_a_number_on_the_page_and_not_a_word(self):
        for field in self.SCALES:
            with self.subTest(field=field):
                _g, text = self.round_trip(field, 2)
                said = next(ln for ln in text.splitlines()
                            if ln.startswith(field))
                self.assertNotIn('"', said)
                self.assertEqual('2', said.split('=')[1].strip())


class APositionThatSendsNothing(unittest.TestCase):
    """The centre of an ON-OFF-(ON) is a real place to leave the handle and
    the game never hears about it. Nothing can measure that: a position
    sending nothing looks exactly like a position that is not there."""

    def built(self, silent_at):
        return capture.states_of('switch3', [7, 8], names=('on', 'off'),
                                 silent_at=silent_at)

    def test_it_goes_in_the_order_it_sits_in(self):
        got = self.built(1)
        self.assertEqual([7, None, 8], [s.get('button') for s in got])
        self.assertIs(False, got[1]['emits_signal'])

    def test_first_and_last_are_reachable(self):
        self.assertEqual([None, 7, 8],
                         [s.get('button') for s in self.built(0)])
        self.assertEqual([7, 8, None],
                         [s.get('button') for s in self.built(2)])

    def test_none_leaves_the_control_as_it_was(self):
        got = self.built(None)
        self.assertEqual([7, 8], [s.get('button') for s in got])
        self.assertNotIn('emits_signal', got[0])

    def test_it_latches_with_the_rest_of_the_switch(self):
        # It is a detent you leave the handle in, so it stays put like
        # every other position on the same switch.
        self.assertIs(True, self.built(1)[1]['latching'])

    def test_it_survives_the_file(self):
        data = fake.raw(groups=[dict(
            fake.group('switch3', [7, 8], names=['on', 'off'], label='Mode'),
            states=self.built(1))])
        back, _ = written(data)
        g = devicemap.Group(**back['group'][0])
        self.assertEqual(3, len(g.places))
        self.assertEqual([False], [p.emits_signal for p in g.places
                                   if not p.emits_signal])
        self.assertEqual([7, 8], g.buttons)
