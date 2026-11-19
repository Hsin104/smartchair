"""
範疇判斷的失敗處理測試（教授 11/16 第 12 點：測試逾時、格式錯誤與服務中斷，並設計保守回應）。
用假的 LLM 物件模擬各種失敗，不呼叫 OpenAI、不需要資料庫：
    python manage.py test api.tests
"""

import asyncio
import json
from unittest import mock

from django.test import SimpleTestCase

from api import physio_agent as pa


class _Reply:
    def __init__(self, content):
        self.content = content
        self.usage_metadata = {'input_tokens': 700, 'output_tokens': 20}


class _FakeLLM:
    """依序回傳 behaviours 裡的結果：字串＝模型回覆內容，Exception＝丟出例外，'hang'＝不回應。"""

    def __init__(self, *behaviours):
        self.behaviours = list(behaviours)
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        b = self.behaviours.pop(0)
        if b == 'hang':
            await asyncio.sleep(3600)
        if isinstance(b, Exception):
            raise b
        return _Reply(b)


def _classify(llm):
    usage = pa._new_usage()
    result = asyncio.run(pa._classify_scope('脖子很痠怎麼辦', 'test-key', usage, llm=llm))
    return result, usage


class ScopeCheckTests(SimpleTestCase):
    def test_normal_in_and_out(self):
        for scope in ('in', 'out'):
            result, usage = _classify(_FakeLLM(json.dumps({'scope': scope, 'category': 'x', 'reason': 'y'})))
            self.assertEqual(result['scope'], scope)
            self.assertEqual(usage['calls'], 1)
            self.assertEqual(usage['input_tokens'], 700)

    def test_bad_json_retries_once_then_succeeds(self):
        llm = _FakeLLM('不是 JSON', json.dumps({'scope': 'in'}))
        result, _ = _classify(llm)
        self.assertEqual(result['scope'], 'in')
        self.assertEqual(llm.calls, 2)

    def test_invalid_scope_value_twice_is_error(self):
        llm = _FakeLLM(json.dumps({'scope': 'maybe'}), json.dumps({}))
        result, _ = _classify(llm)
        self.assertEqual(result['scope'], 'error')
        self.assertIn('scope 值不合法', result['reason'])

    def test_timeout_twice_is_error(self):
        with mock.patch.object(pa, '_SCOPE_TIMEOUT_SECONDS', 0.05):
            result, _ = _classify(_FakeLLM('hang', 'hang'))
        self.assertEqual(result['scope'], 'error')
        self.assertIn('逾時', result['reason'])

    def test_service_down_twice_is_error(self):
        err = ConnectionError('Connection refused')
        result, _ = _classify(_FakeLLM(err, err))
        self.assertEqual(result['scope'], 'error')

    def test_quota_exhausted_is_raised_not_hidden(self):
        """額度用完不能被當成一般失敗吞掉，要讓 App 看到「額度已達上限」的明確錯誤。"""
        with self.assertRaises(Exception):
            _classify(_FakeLLM(RuntimeError('Error code: 429 - insufficient_quota')))

    def test_invalid_key_is_raised_not_retried(self):
        """金鑰無效重試也不會好，不能回「請稍後再試」誤導使用者（故障測試 D1 發現）。"""
        with self.assertRaises(Exception):
            _classify(_FakeLLM(RuntimeError("Error code: 401 - {'code': 'invalid_api_key'}")))


class ConservativeAnswerTests(SimpleTestCase):
    def _answer(self, scope):
        async def fake_classify(*args, **kwargs):
            return scope

        async def react_must_not_run(*args, **kwargs):
            raise AssertionError('範疇判斷失敗時不可以進 ReAct 迴圈')

        with mock.patch.object(pa, '_classify_scope', fake_classify), \
                mock.patch.object(pa, '_run_react', react_must_not_run):
            return asyncio.run(pa._answer('問題', '脖子很痠怎麼辦', 'test-key', pa._new_usage()))

    def test_error_gives_conservative_reply_and_logs_reason(self):
        output, steps = self._answer({'scope': 'error', 'category': '', 'reason': '範疇判斷失敗：逾時 / 逾時'})
        self.assertEqual(output, pa.SCOPE_UNAVAILABLE)
        self.assertEqual(steps[0]['action'], 'scope_check')
        self.assertIn('逾時', steps[0]['observation'])

    def test_conservative_reply_is_not_tagged_as_missing_citation(self):
        self.assertEqual(pa._validate_response(pa.SCOPE_UNAVAILABLE), pa.SCOPE_UNAVAILABLE)

    def test_out_of_scope_refuses(self):
        output, _ = self._answer({'scope': 'out', 'category': '藥物', 'reason': '問止痛藥'})
        self.assertEqual(output, pa.REFUSAL_SENTENCE)


class TokenUsageTests(SimpleTestCase):
    def test_usage_step_sums_calls(self):
        usage = pa._new_usage()
        pa._add_usage(usage, _Reply('a'))
        r = _Reply('b')
        r.usage_metadata = {'input_tokens': 1200, 'output_tokens': 300, 'input_token_details': {'cache_read': 1024}}
        pa._add_usage(usage, r)
        step = pa._usage_step(usage)
        self.assertEqual(step['action'], 'token_usage')
        self.assertEqual(step['action_input'], {'calls': 2, 'input_tokens': 1900, 'cached_tokens': 1024,
                                                'output_tokens': 320})
