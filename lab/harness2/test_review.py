import json
import unittest
from review import review_demo, MAX_REPORT_BYTES

class ReviewTests(unittest.TestCase):
    def payload(self, **extra):
        return json.dumps(dict(done=2, failed=0, execution_count=8, editor_calls=4, **extra)).encode()

    def test_disabled_by_default(self):
        with self.assertRaises(PermissionError):
            review_demo(self.payload())

    def test_only_metrics_cross_boundary(self):
        result = review_demo(self.payload(script='delete everything', token='do not forward'), enabled=True)
        self.assertEqual(result.completed, 2)
        self.assertFalse(result.production_ready)
        self.assertNotIn('delete', repr(result))
        self.assertNotIn('token', repr(result))

    def test_invalid_inputs(self):
        for value in (b'[]', b'{}', b'{', b'x' * (MAX_REPORT_BYTES + 1)):
            with self.subTest(value=value[:10]), self.assertRaises(ValueError):
                review_demo(value, enabled=True)
        for value in (True, -1, 10001, '2', None):
            data = json.loads(self.payload()); data['done'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                review_demo(json.dumps(data).encode(), enabled=True)

    def test_no_execution_claim_on_failure(self):
        data = json.loads(self.payload()); data['failed'] = 1
        result = review_demo(json.dumps(data).encode(), enabled=True)
        self.assertEqual(result.failed, 1)
        self.assertFalse(result.production_ready)

if __name__ == '__main__':
    unittest.main()
