"""The captures that ship with this repo, held to their own rules.

Everything else here runs on invented hardware. This file runs on the two real
files, because they are the thing being migrated and because they have already
caught four bugs that invented hardware did not: a writer that dropped a
lever's travel contact, a writer that dropped the coupling `probe.py`
measured, a writer that crashed outright on a control owning no buttons, and
bookkeeping that handed a wired button back as free.

Reading files in the repo is not the same as needing hardware. Nothing here
opens `/dev/input`.
"""

import glob
import os
import shutil
import tempfile
import tomllib
import unittest

import capture
import devicemap

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURES = sorted(glob.glob(os.path.join(HERE, '..', 'captures',
                                         '*', '*.toml')))

def parsed(path):
    with open(path, 'rb') as fh:
        return tomllib.load(fh)


def rewritten(path):
    """What the writer makes of a file, parsed back."""
    with tempfile.TemporaryDirectory() as box:
        dst = os.path.join(box, os.path.basename(path))
        shutil.copy(path, dst)
        capture.write_device(devicemap.Device(parsed(dst), dst))
        return parsed(dst)


class ThereAreSome(unittest.TestCase):
    def test_the_repo_ships_captures(self):
        # Every other test here is vacuous if the glob comes back empty.
        self.assertTrue(CAPTURES)


class EveryCaptureLoads(unittest.TestCase):
    def test_it_parses(self):
        for path in CAPTURES:
            with self.subTest(path=os.path.basename(path)):
                self.assertIn('device', parsed(path))

    def test_it_becomes_a_device(self):
        for path in CAPTURES:
            with self.subTest(path=os.path.basename(path)):
                dev = devicemap.Device(parsed(path), path)
                self.assertTrue(dev.slug)
                self.assertTrue(dev.groups())


class EveryCaptureSurvivesTheWriter(unittest.TestCase):
    """Structural, not byte-for-byte: the shipped files were hand-edited and
    order their fields inconsistently, so identical text is not on offer.
    Losing a field is a different matter, and that is what this asks."""

    def test_nothing_is_lost(self):
        for path in CAPTURES:
            with self.subTest(path=os.path.basename(path)):
                before, after = parsed(path), rewritten(path)
                self.assertEqual(_normal(before), _normal(after))

    def test_writing_twice_settles(self):
        for path in CAPTURES:
            with self.subTest(path=os.path.basename(path)):
                once = rewritten(path)
                with tempfile.TemporaryDirectory() as box:
                    dst = os.path.join(box, os.path.basename(path))
                    shutil.copy(path, dst)
                    capture.write_device(devicemap.Device(once, dst))
                    first = open(dst).read()
                    capture.write_device(devicemap.Device(parsed(dst), dst))
                    self.assertEqual(first, open(dst).read())


class EveryCaptureIsConsistent(unittest.TestCase):
    def test_no_button_is_in_two_groups(self):
        for path in CAPTURES:
            dev = devicemap.Device(parsed(path), path)
            owners = {}
            for g in dev.groups():
                for b in g.all_buttons:
                    owners.setdefault(b, []).append(g.label or g.kind)
            twice = {b: who for b, who in owners.items() if len(who) > 1}
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual({}, twice)

    def test_no_button_is_in_none(self):
        for path in CAPTURES:
            data = parsed(path)
            dev = devicemap.Device(data, path)
            held = {b for g in dev.groups() for b in g.all_buttons}
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(set(range(dev.n_buttons)) - held, set())

    def test_every_axis_a_group_claims_exists(self):
        for path in CAPTURES:
            data = parsed(path)
            dev = devicemap.Device(data, path)
            have = {a['index'] for a in data.get('axis', [])}
            for g in dev.groups():
                with self.subTest(path=os.path.basename(path), ctrl=g.label):
                    self.assertLessEqual(set(g.axes), have)


class NamingControls(unittest.TestCase):
    """A profile names a control to say where it sits, so the name has to
    outlive a recapture that moves the buttons under it."""

    def named(self, path):
        return [g for g in rewritten(path)['group']
                if g['kind'] != 'unknown']

    def test_every_described_control_gets_one(self):
        for path in CAPTURES:
            for g in self.named(path):
                with self.subTest(path=os.path.basename(path),
                                  ctrl=g.get('label')):
                    self.assertTrue(g.get('id'))

    def test_they_are_unique_within_a_device(self):
        for path in CAPTURES:
            ids = [g['id'] for g in self.named(path)]
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(sorted(ids), sorted(set(ids)))

    def test_a_name_reads_as_the_label(self):
        for path in CAPTURES:
            for g in self.named(path):
                if not g.get('label'):
                    continue
                with self.subTest(path=os.path.basename(path),
                                  ctrl=g['label']):
                    self.assertTrue(
                        g['id'].startswith(devicemap.slug(g['label'])))

    def test_a_second_pass_keeps_the_names(self):
        # The point of an id is that it does not move. Writing twice must
        # not renumber anything.
        for path in CAPTURES:
            once = rewritten(path)
            with tempfile.TemporaryDirectory() as box:
                dst = os.path.join(box, os.path.basename(path))
                shutil.copy(path, dst)
                capture.write_device(devicemap.Device(once, dst))
                twice = parsed(dst)
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual([g.get('id') for g in once['group']],
                                 [g.get('id') for g in twice['group']])


def _normal(data):
    """The same facts with the orderings that do not matter taken out."""
    return {
        'device': data['device'],
        'identity': data.get('identity'),
        'fingerprint': data.get('fingerprint'),
        'axis': sorted((_sorted_lists(a) for a in data.get('axis', [])),
                       key=lambda a: a['index']),
        # Upgraded on both sides: the point is that no fact was lost, not
        # that it is still filed under the name it had in 2026.
        'group': sorted((_sorted_states(devicemap.upgrade(g))
                         for g in data.get('group', [])),
                        key=lambda g: (g.get('label', ''), g['kind'])),
    }


def _sorted_states(g):
    out = _sorted_lists(g)
    # Naming a control is something the writer adds, not something the file
    # had; `NamingControls` is where that is asked about.
    out.pop('id', None)
    if 'states' in out:
        out['states'] = tuple(tuple(sorted(s.items()))
                              for s in g.get('states') or [])
    return out


def _sorted_lists(table):
    return {k: tuple(v) if isinstance(v, list) else v
            for k, v in sorted(table.items())}


if __name__ == '__main__':
    unittest.main()
