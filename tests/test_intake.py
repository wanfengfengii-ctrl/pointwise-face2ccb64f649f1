import json
from dataclasses import replace
from fractions import Fraction

from intake.receive import receive
from issue.envelope import decode_envelope, encode_envelope, fingerprint_body
from tests.fixtures import WorkflowCase, segment


class IntakeTests(WorkflowCase):
    def setUp(self):
        super().setUp()
        self.original = self.issue('intake', segment('A', 0, 6, 0, terminal=True))

    def conflicting_payload(self):
        envelope = decode_envelope(self.original.payload)
        row, = envelope.profile.segments
        changed = replace(row, left_height=Fraction(2))
        return encode_envelope(replace(envelope, profile=replace(envelope.profile, segments=(changed,))))

    def verify_original(self):
        self.assertEqual(self.catalog.get(self.original.bundle_id).payload, self.original.payload)
        self.assertEqual(self.offline.execute('SELECT count(*) FROM accepted_bundles').fetchone()[0], 1)
        self.assertEqual(self.inspect('original-only', [self.original.bundle_id]).report.status, 'clear')

    def test_reject_conflicting_body(self):
        self.accept(self.original)
        for payload in (self.conflicting_payload(), b'broken JSON'):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    receive(self.catalog, payload)
        self.verify_original()

    def test_identical_replay(self):
        self.accept(self.original)
        formatted = json.dumps(json.loads(self.original.payload), indent=2).encode('utf-8')
        self.assertNotEqual(formatted, self.original.payload)
        self.assertEqual(receive(self.catalog, formatted), self.original.bundle_id)
        self.offline.close()
        self.open_offline()
        self.assertEqual(receive(self.catalog, self.original.payload), self.original.bundle_id)
        self.verify_original()

    def test_valid_conflict(self):
        self.accept(self.original)
        changed = self.conflicting_payload()
        self.assertEqual(decode_envelope(changed).bundle_id, self.original.bundle_id)
        with self.assertRaisesRegex(ValueError, 'conflicting content'):
            receive(self.catalog, changed)
        self.verify_original()

    def test_bad_digest(self):
        data = json.loads(self.original.payload)
        data['body']['segments'][0]['left_height'] = '9'
        payload = json.dumps(data).encode('utf-8')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            receive(self.catalog, payload)
        with self.assertRaises(KeyError):
            self.catalog.get(self.original.bundle_id)
        self.accept(self.original)
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            receive(self.catalog, payload)
        self.verify_original()

    def test_bad_binding_or_profile_with_valid_digest(self):
        binding = json.loads(self.original.payload)
        binding['body']['revision_id'] += 1
        invalid_range = json.loads(self.original.payload)
        invalid_range['body']['segments'][0]['end'] = '-1'
        for data, reason in ((binding, 'body binding'), (invalid_range, 'invalid segment bounds')):
            with self.subTest(reason=reason):
                data['digest'] = fingerprint_body(data['body'])
                with self.assertRaisesRegex(ValueError, reason):
                    receive(self.catalog, json.dumps(data).encode('utf-8'))
        with self.assertRaises(KeyError):
            self.catalog.get(self.original.bundle_id)
