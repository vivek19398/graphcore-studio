import copy
import json
import os
import types
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'python'))
from studio.engine import validate, compile_workflow, structured, render, WorkflowError, pydantic_available, register_tool, TOOLS, chat_messages, invoke_model, resolve_model
from studio.server import Store
from graphcore import Graph, END, GraphCoreError

class StudioTests(unittest.TestCase):
    def test_named_models_resolve_and_validate(self):
        models = {'model1': 'deepseek/deepseek-v4-pro-0813', 'model2': 'openai/gpt-4o-mini'}
        self.assertEqual(resolve_model({'model': '$model1'}, models), models['model1'])
        self.assertEqual(resolve_model({'model': '$model2'}, models), models['model2'])
        self.assertEqual(resolve_model({'model': 'google/gemini-2.5-flash'}, models), 'google/gemini-2.5-flash')
        with self.assertRaisesRegex(WorkflowError, 'Unknown model variable'):
            resolve_model({'model': '$missing'}, models)

    def test_store_persists_named_models(self):
        with tempfile.TemporaryDirectory() as path:
            store = Store(path)
            try:
                self.assertEqual(store.update_models({'model1': 'deepseek/deepseek-v4-pro-0813'}),
                                 {'model1': 'deepseek/deepseek-v4-pro-0813'})
                with self.assertRaisesRegex(ValueError, 'simple identifiers'):
                    store.update_models({'bad-name': 'openai/gpt-4o-mini'})
            finally:
                store.close()
            reopened = Store(path)
            try:
                self.assertEqual(reopened.models['model1'], 'deepseek/deepseek-v4-pro-0813')
            finally:
                reopened.close()

    def flow(self, name='01-research.json'):
        return json.loads((ROOT / 'studio/templates' / name).read_text())

    def test_templates_compile_and_run(self):
        for path in (ROOT / 'studio/templates').glob('*.json'):
            flow = json.loads(path.read_text())
            with self.subTest(template=path.name):
                self.assertEqual(validate(flow), [])
                with compile_workflow(flow) as graph:
                    result = graph.invoke(flow['inputs'])
                    self.assertTrue(result.suspended or 'output' in result.state)

    def test_native_false_route(self):
        flow = self.flow()
        events = []
        with compile_workflow(flow, lambda kind, **data: events.append((kind, data))) as graph:
            result = graph.invoke(dict(flow['inputs'], needs_review=False))
        self.assertFalse(result.suspended)
        self.assertIn('output', result.state)
        started = [data['node'] for kind, data in events if kind == 'node.started']
        self.assertIn('review_gate', started)
        self.assertNotIn('approval', started)

    def test_native_condition_strict_types(self):
        with Graph('native') as graph:
            graph.add_condition('branch', 'flag', True, 'yes', 'no')
            graph.add_node('yes', lambda s,c: {'answer': True}).add_edge('yes', END)
            graph.add_node('no', lambda s,c: {'answer': False}).add_edge('no', END)
            graph.set_entry('branch')
            self.assertTrue(graph.invoke({'flag': True}).state['answer'])
            self.assertFalse(graph.invoke({'flag': 'true'}).state['answer'])
            with self.assertRaisesRegex(GraphCoreError, 'missing'):
                graph.invoke({})

    def test_cooperative_native_cancel(self):
        with Graph() as graph:
            def cancel(s,c):
                graph.cancel()
                return {'uncommitted': True}
            graph.add_node('a', cancel).add_edge('a', END).set_entry('a')
            with self.assertRaisesRegex(GraphCoreError, 'cancelled'):
                graph.invoke()

    def test_validation_catches_missing_branch(self):
        flow = self.flow()
        flow['edges'] = [edge for edge in flow['edges'] if edge.get('port') != 'false']
        self.assertTrue(any('both true and false' in e for e in validate(flow)))

    def test_malformed_documents_return_errors(self):
        for mutation in [None, {}, {'nodes':[]}, {'format':'graphcore.studio.v1','nodes':[{'id':[]}],'edges':[]}]:
            self.assertTrue(validate(mutation))
        flow = self.flow(); flow['nodes'][0]['type'] = []
        self.assertTrue(validate(flow))

    def test_unreachable_node_rejected(self):
        flow = self.flow(); extra = copy.deepcopy(flow['nodes'][-1]); extra['id'] = 'unused'; flow['nodes'].append(extra)
        self.assertTrue(any('not reachable' in e for e in validate(flow)))

    def test_missing_template_variable_fails(self):
        with self.assertRaisesRegex(WorkflowError, 'missing'):
            render('{{not_here}}', {})
        self.assertEqual(render('{{record.summary}}', {'record':{'summary':'yes'}}), 'yes')

    def test_model_messages_render_variables_and_malformed_roles_fail_validation(self):
        flow = self.flow('05-model.json')
        model = next(n for n in flow['nodes'] if n['type'] == 'model')
        self.assertEqual(chat_messages(model['config'], flow['inputs']), [
            {'role':'system','content':'Explain ideas clearly for A new developer. Be concise.'},
            {'role':'user','content':'What makes a workflow graph useful?'}])
        model['config']['messages'][0]['role'] = []
        self.assertTrue(any('each message needs' in error for error in validate(flow)))

    def test_initial_model_provider_is_openrouter_only(self):
        flow=self.flow('05-model.json')
        model=next(n for n in flow['nodes'] if n['type']=='model')
        model['config']['provider']='openai'
        self.assertTrue(any('supported chat-model provider' in error for error in validate(flow)))

    def test_model_uses_official_openrouter_sdk_through_python_wrapper(self):
        seen = {}
        class Chat:
            def send(self, **kwargs):
                seen['request'] = kwargs
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"answer":"hello"}'))])
        class FakeOpenRouter:
            def __init__(self, **kwargs): seen['client'] = kwargs
            def __enter__(self): self.chat=Chat(); return self
            def __exit__(self,*args): pass
        sdk=types.ModuleType('openrouter'); sdk.OpenRouter=FakeOpenRouter
        with patch.dict('sys.modules', {'openrouter':sdk}), patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-secret'}):
            result=invoke_model({'provider':'openrouter','model':'openai/example-chat','temperature':.4,
                'max_tokens':88,'timeout':12,'json_output':True,'messages':[{'role':'user','content':'Say {{word}}'}]}, {'word':'hello'})
        self.assertEqual(result,{'answer':'hello'})
        self.assertEqual(seen['client'],{'api_key':'test-secret'})
        self.assertEqual(seen['request']['messages'],[{'role':'user','content':'Say hello'}])
        self.assertEqual(seen['request']['model'],'openai/example-chat')
        self.assertEqual(seen['request']['temperature'],.4)
        self.assertEqual(seen['request']['max_completion_tokens'],88)
        self.assertEqual(seen['request']['timeout_ms'],12000)
        self.assertEqual(seen['request']['response_format'],{'type':'json_object'})

        with patch.dict('sys.modules', {'openrouter':sdk}), patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-secret'}):
            invoke_model({'provider':'openrouter','model':'deepseek/example','reasoning_effort':'low',
                'messages':[{'role':'user','content':'hello'}]}, {})
        self.assertEqual(seen['request']['reasoning_effort'],'low')
        with patch.dict('sys.modules', {'openrouter':sdk}), patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-secret'}):
            invoke_model({'provider':'openrouter','model':'$model2',
                'messages':[{'role':'user','content':'hello'}]}, {}, {'model2':'google/gemini-2.5-flash'})
        self.assertEqual(seen['request']['model'],'google/gemini-2.5-flash')

    def test_model_retries_empty_reasoning_response_and_reads_typed_text_blocks(self):
        seen=[]
        class Chat:
            def send(self, **kwargs):
                seen.append(kwargs)
                content=None if len(seen)==1 else [{'type':'text','text':'usable answer'}]
                return types.SimpleNamespace(choices=[types.SimpleNamespace(
                    finish_reason='length', message=types.SimpleNamespace(content=content, reasoning='hidden'))])
        class FakeOpenRouter:
            def __init__(self, **kwargs): pass
            def __enter__(self): self.chat=Chat(); return self
            def __exit__(self,*args): pass
        sdk=types.ModuleType('openrouter'); sdk.OpenRouter=FakeOpenRouter
        with patch.dict('sys.modules', {'openrouter':sdk}), patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-secret'}):
            result=invoke_model({'provider':'openrouter','model':'deepseek/example','max_tokens':100,
                'messages':[{'role':'user','content':'hello'}]}, {})
        self.assertEqual(result,'usable answer')
        self.assertEqual(len(seen),2)
        self.assertEqual(seen[0]['max_completion_tokens'],100)
        self.assertEqual(seen[1]['max_completion_tokens'],200)
        self.assertEqual(seen[1]['reasoning_effort'],'none')

    def test_schema_strict_contract(self):
        fields = [{'name':'name','type':'string'},{'name':'score','type':'number'}]
        self.assertEqual(structured('{"name":"demo","score":0.5}',fields)['score'], .5)
        for value in [{'name':'demo','score':True},{'score':1},{'name':'demo','score':1,'extra':'bad'}]:
            with self.assertRaises(WorkflowError): structured(value,fields)

    @unittest.skipUnless(pydantic_available(), 'Pydantic optional dependency not installed')
    def test_pydantic_real_engine(self):
        flow = self.flow('02-structured.json')
        flow['nodes'][2]['config']['engine'] = 'pydantic'
        with compile_workflow(flow) as graph:
            result = graph.invoke(flow['inputs'])
            self.assertEqual(result.state['validated']['confidence'], .95)

    def test_registered_python_tool(self):
        register_tool('test_custom', lambda value, config: {'echo':value})
        flow = self.flow('03-tools.json'); flow['nodes'][1]['config']['tool'] = 'test_custom'
        try:
            with compile_workflow(flow) as graph:
                result = graph.invoke(flow['inputs'])
                self.assertEqual(result.state['keywords']['echo'], flow['inputs']['input'])
        finally: TOOLS.pop('test_custom')

    def wait(self, store, ident):
        for _ in range(300):
            result=store.snapshot(ident)
            if result['status'] not in ('queued','running','cancelling'): return result
            time.sleep(.01)
        self.fail('Run did not finish')

    def test_store_restart_resume_and_duplicate_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            flow=self.flow()
            ident=store.start(flow,flow['inputs'])
            self.assertEqual(self.wait(store,ident)['status'],'suspended')
            store.close()
            restored=Store(directory)
            try:
                self.assertEqual(restored.snapshot(ident)['status'],'suspended')
                restored.continue_run(ident,'resume',True)
                with self.assertRaises(ValueError): restored.continue_run(ident,'resume',True)
                result=self.wait(restored,ident)
                self.assertEqual(result['status'],'completed')
                self.assertTrue(result['state']['review_response'])
            finally: restored.close()

    def test_store_pins_workflow_and_recovers_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            try:
                flow=self.flow('03-tools.json')
                flow['nodes'][1]['config']['tool']='test_retry'
                counter=[0]
                def flaky(value, config):
                    counter[0]+=1
                    if counter[0]==1: raise ValueError('temporary failure')
                    return ['recovered']
                register_tool('test_retry',flaky)
                ident=store.start(flow,flow['inputs'])
                flow['name']='Changed draft'
                self.assertEqual(self.wait(store,ident)['status'],'failed')
                self.assertNotEqual(store.snapshot(ident)['name'],flow['name'])
                store.continue_run(ident,'recover')
                self.assertEqual(self.wait(store,ident)['status'],'completed')
            finally:
                store.close(); TOOLS.pop('test_retry',None)

if __name__=='__main__': unittest.main()
