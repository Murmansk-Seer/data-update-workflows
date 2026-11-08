"""Evaluate the actual caller condition; the updater owns parser-aware skipping."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def config_job_condition(workflow: str) -> str:
    job = workflow.split('\n  update-config-sources:', 1)[1]
    match = re.search(r'    if: >-\s*(\$\{\{.*?\}\})', job, re.S)
    if match is None:
        raise AssertionError('Configuration caller condition is missing')
    return match[1][3:-2].strip()


def permits(condition: str, **changes: object) -> bool:
    values = {
        'inputs.chip-icons-only': False,
        'inputs.force-update-config': False,
        'needs.check-unity-assets.result': 'success',
        'needs.update-main-assets.result': 'skipped',
        'needs.update-pet-assets.result': 'skipped',
        'needs.update-main-assets.outputs.has_update': 'false',
        'needs.update-pet-assets.outputs.has_update': 'false',
        'needs.check-unity-assets.outputs.need_update_config': 'false',
    }
    values.update(changes)
    expression = ' '.join(condition.split()).replace('always()', 'True')
    for key in sorted(values, key=len, reverse=True):
        expression = expression.replace(key, repr(values[key]))
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    expression = re.sub(r'!(?!=)', ' not ', expression).strip()
    parsed = ast.parse(expression, mode='eval')
    allowed = (ast.Expression, ast.BoolOp, ast.UnaryOp, ast.Compare, ast.Constant,
               ast.And, ast.Or, ast.Not, ast.Eq)
    if any(not isinstance(node, allowed) for node in ast.walk(parsed)):
        raise AssertionError('Unsupported caller expression in regression evaluator')
    return bool(eval(compile(parsed, '<caller condition>', 'eval'), {'__builtins__': {}}))


class ConfigurationCallerTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / '.github/workflows/update.yml').read_text()
        self.condition = config_job_condition(self.workflow)

    def test_stable_asset_versions_still_reach_parser_aware_updater(self):
        self.assertTrue(permits(self.condition))

    def test_successful_or_skipped_assets_reach_updater(self):
        for main in ('success', 'skipped'):
            for pet in ('success', 'skipped'):
                with self.subTest(main=main, pet=pet):
                    self.assertTrue(permits(self.condition, **{
                        'needs.update-main-assets.result': main,
                        'needs.update-pet-assets.result': pet,
                    }))

    def test_failed_or_cancelled_prerequisite_blocks_even_forced_update(self):
        for key in ('needs.check-unity-assets.result',
                    'needs.update-main-assets.result', 'needs.update-pet-assets.result'):
            for result in ('failure', 'cancelled'):
                with self.subTest(key=key, result=result):
                    self.assertFalse(permits(self.condition, **{
                        key: result, 'inputs.force-update-config': True,
                    }))

    def test_chip_only_recovery_does_not_run_config_or_dispatch(self):
        self.assertFalse(permits(self.condition, **{'inputs.chip-icons-only': True}))

    def test_dispatch_still_requires_actual_configuration_commit(self):
        dispatch = self.workflow.split('- name: Dispatch api-data build', 1)[1]
        dispatch = dispatch.split('  report:', 1)[0]
        self.assertIn("steps.update.outputs.has_update == 'true'", dispatch)
        update_step = self.workflow.split('- name: Update config-sources', 1)[1]
        self.assertIn('uv run update-config-sources', update_step)


if __name__ == '__main__':
    unittest.main()
