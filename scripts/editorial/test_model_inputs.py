"""Lossless request-scoped model input projection contracts."""
import copy
import json
import unittest

from model_inputs import model_input_sizes, project_model_input, restore_model_input


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def wire_bytes(value):
    return len(json.dumps(encoded(value), ensure_ascii=False, allow_nan=False).encode('utf-8'))


class ModelInputTests(unittest.TestCase):
    def test_repeated_long_values_project_shorter_and_restore_exactly(self):
        long_text = ('公称値2.0kg。条件付きURL https://maker.example/item?mode=exact を保持。' * 12)
        repeated_object = {'facts': [long_text], 'number': '2.0kg', 'qualified': '公称値であり実測値ではない'}
        repeated_list = [{'url': 'https://maker.example/%d' % i, 'value': i} for i in range(20)]
        value = {'catalog': repeated_list, 'products': copy.deepcopy(repeated_list),
                 'CLAUDE': long_text, 'SKILL': long_text,
                 'first': repeated_object, 'second': copy.deepcopy(repeated_object)}
        original = copy.deepcopy(value)
        projected = project_model_input(value)
        self.assertEqual(restore_model_input(projected), original)
        self.assertEqual(value, original)
        self.assertLess(wire_bytes(projected), wire_bytes(value))
        self.assertIn('reference', encoded(projected).lower())
        self.assertEqual(projected, project_model_input(value))
        self.assertEqual(model_input_sizes(value), {
            'plainBytes': wire_bytes(value),
            'projectedBytes': wire_bytes(projected),
            'projected': True,
        })

    def test_unique_or_short_repetitions_remain_original_when_envelope_is_not_smaller(self):
        for value in ({'a': 'x' * 255, 'b': 'x' * 255},
                      {'a': 'x' * 400, 'b': 'different-' + 'y' * 400},
                      {'small': [{'x': 1}, {'x': 1}]}):
            original = copy.deepcopy(value)
            projected = project_model_input(value)
            self.assertEqual(projected, original)
            self.assertEqual(restore_model_input(projected), original)
            self.assertFalse(model_input_sizes(value)['projected'])

    def test_reference_like_source_keys_are_never_misdecoded(self):
        long_text = 'qualified fact 17.5 cm https://maker.example/spec ' * 10
        value = {'literal': {'$ref': 'r1'}, 'a': long_text, 'b': long_text}
        self.assertEqual(restore_model_input(project_model_input(value)), value)
        self.assertEqual(restore_model_input(value), value)

    def test_literal_reserved_envelope_shape_is_not_decoded(self):
        value = {'$modelInputProjection': {'version': 1, 'referenceKey': '$modelInputRef',
                                           'instruction': 'literal source content'},
                 'definitions': {'r1': {'fact': 'literal'}},
                 'data': {'$modelInputRef': 'r1'}}
        self.assertEqual(project_model_input(value), value)
        self.assertEqual(restore_model_input(value), value)


if __name__ == '__main__':
    unittest.main()
