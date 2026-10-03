import json
import tempfile
import unittest
from pathlib import Path
from studio.tables import LocalTables
from studio.engine import compile_workflow, validate

class TableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tables = LocalTables(self.temp.name)

    def test_exact_summary_and_immutable_reference(self):
        ref = self.tables.add('sales.csv', 'name,amount\na,0.1\nb,0.2\nc,\n', {'amount':'decimal'})
        self.assertNotIn('rows', ref)
        result = self.tables.summarize(ref, 'amount')
        self.assertEqual(result['sum'], '0.3')
        self.assertEqual((result['count'], result['null_count']), (2,1))
        self.assertEqual(self.tables.preview(ref['id'])['rows'][0]['amount'], '0.1')
        self.assertEqual(self.tables.list(), [ref])
        self.assertEqual(ref, self.tables.add('sales.csv', 'name,amount\na,0.1\nb,0.2\nc,\n', {'amount':'decimal'}))
        path = Path(self.temp.name)/(ref['id']+'.json')
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'integrity'): self.tables.read(ref['id'])

    def test_wide_decimal_exponents_remain_exact(self):
        from decimal import Decimal
        tiny = '1'*90 + 'e-189'
        ref = self.tables.add('wide.csv', 'amount\n1e100\n'+tiny+'\n', {'amount':'decimal'})
        expected = '1' + '0'*100 + '.' + '0'*99 + '1'*90
        self.assertEqual(Decimal(self.tables.summarize(ref,'amount')['sum']), Decimal(expected))
        for value, kind in [('9'*101,'integer'), ('0e999999999','decimal')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.tables.add('invalid.csv','amount\n'+value,{'amount':kind})

    def test_inspection_is_bounded_and_does_not_persist(self):
        preview = self.tables.inspect('quoted.csv', '"customer,name",amount\n"Acme, Inc",0.1\n'+'Beta,0.2\n'*8)
        self.assertEqual(preview['row_count'],9)
        self.assertEqual(len(preview['rows']),5)
        self.assertEqual(preview['columns'][0]['name'],'customer,name')
        self.assertEqual(preview['rows'][0]['customer,name'],'Acme, Inc')
        self.assertTrue(preview['truncated'])
        self.assertEqual(self.tables.list(),[])
        with self.assertRaises(ValueError): self.tables.inspect('bad.csv','a,b\n1')
        self.assertEqual(self.tables.list(),[])

    def test_invalid_sources_and_types(self):
        for name,text,types in [('x.csv','a,a\n1,2',{}), ('x.csv','a,b\n1',{}),
                                ('x.csv','a\nNaN',{'a':'decimal'}), ('../x.csv','a\n1',{}),
                                ('x.csv','a\n1',{'missing':'integer'}), ('x.csv','a\n1.1',{'a':'integer'})]:
            with self.subTest(text=text), self.assertRaises(ValueError): self.tables.add(name,text,types)
        with self.assertRaises(ValueError): self.tables.preview('../file')

    def test_native_data_graph_and_bounded_preview(self):
        ref = self.tables.add('numbers.csv','amount\n'+'1\n'*25,{'amount':'integer'})
        self.assertEqual(len(self.tables.preview(ref['id'])['rows']),20)
        self.assertTrue(self.tables.preview(ref['id'])['truncated'])
        workflow={'format':'graphcore.studio.v1','nodes':[
            {'id':'start','type':'input'},
            {'id':'calc','type':'data','config':{'input_field':'table','column':'amount','output_key':'summary'}},
            {'id':'end','type':'output','config':{'template':'{{summary.sum}}'}}],
            'edges':[{'source':'start','target':'calc'},{'source':'calc','target':'end'}]}
        self.assertEqual(validate(workflow),[])
        with compile_workflow(workflow,summarize=self.tables.summarize) as graph:
            result=graph.invoke({'table':ref})
        self.assertEqual(result.state['output'],'25')
