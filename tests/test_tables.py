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

    def test_typed_filters_nulls_and_provenance(self):
        ref = self.tables.add('sales.csv','name,amount,active\nAcme,0.10,true\nBeta,0.20,false\nGamma,,true\n',{'amount':'decimal','active':'boolean'})
        result = self.tables.filter(ref,'amount','gte','0.2')
        self.assertEqual(result['row_count'],1)
        self.assertEqual(self.tables.preview(result['id'])['rows'][0]['name'],'Beta')
        self.assertEqual(result['provenance']['parent_id'],ref['id'])
        self.assertEqual(self.tables.filter(ref,'amount','gte','0.2'),result)
        for operator,value,count in [('gt','0.1',1),('gte','0.1',2),('lt','0.2',1),('lte','0.2',2)]:
            with self.subTest(operator=operator):
                self.assertEqual(self.tables.filter(ref,'amount',operator,value)['row_count'],count)
        self.assertEqual(self.tables.filter(ref,'amount','eq','0.1')['row_count'],1)
        self.assertEqual(self.tables.filter(ref,'amount','ne','0.1')['row_count'],1)
        self.assertEqual(self.tables.filter(ref,'amount','is_null')['row_count'],1)
        self.assertEqual(self.tables.filter(ref,'amount','not_null')['row_count'],2)
        self.assertEqual(self.tables.filter(ref,'active','eq','true')['row_count'],2)
        self.assertEqual(self.tables.filter(ref,'name','contains','Ac')['row_count'],1)
        empty = self.tables.filter(ref,'amount','gt','100')
        self.assertEqual(self.tables.summarize(empty,'amount')['sum'],'0')
        self.assertEqual(self.tables.read(ref['id'])['rows'][0]['name'],'Acme')
        for column,operator,value in [('missing','eq','a'),('name','gt','A'),('active','contains','true'),('amount','eq','NaN'),('amount','eq',''),('amount','bad','1')]:
            with self.subTest(operator=operator,column=column), self.assertRaises(ValueError):
                self.tables.filter(ref,column,operator,value)

    def test_filter_native_graph_then_summary(self):
        ref=self.tables.add('values.csv','amount\n0.1\n0.2\n0.3\n',{'amount':'decimal'})
        workflow={'format':'graphcore.studio.v1','nodes':[
            {'id':'start','type':'input'},
            {'id':'filter','type':'data_filter','config':{'input_field':'table','column':'amount','operator':'gte','value':'0.2','output_key':'filtered'}},
            {'id':'summary','type':'data','config':{'input_field':'filtered','column':'amount','output_key':'stats'}},
            {'id':'end','type':'output','config':{'template':'{{stats.sum}}'}}],
            'edges':[{'source':'start','target':'filter'},{'source':'filter','target':'summary'},{'source':'summary','target':'end'}]}
        with compile_workflow(workflow,summarize=self.tables.summarize,filter_table=self.tables.filter) as graph:
            result=graph.invoke({'table':ref})
        self.assertEqual(result.state['output'],'0.5')
        self.assertNotIn('rows',result.state['filtered'])
        workflow['nodes'][1]['config']['value']=True
        self.assertTrue(validate(workflow))

    def test_grouped_totals_nulls_and_first_seen_order(self):
        ref=self.tables.add('sales.csv','team,amount\nB,0.1\nA,0.2\nB,0.2\nA,\n,0.4\nC,\n',{'amount':'decimal'})
        grouped=self.tables.group(ref,'team','amount')
        rows=self.tables.read(grouped['id'])['rows']
        self.assertEqual([r['group_key'] for r in rows],['B','A',None,'C'])
        self.assertEqual(rows[0]['sum'],'0.3')
        self.assertEqual((rows[1]['row_count'],rows[1]['count'],rows[1]['null_count']),(2,1,1))
        self.assertEqual((rows[3]['sum'],rows[3]['min'],rows[3]['max']),('0',None,None))
        self.assertEqual(grouped['provenance']['parent_id'],ref['id'])
        self.assertEqual(grouped,self.tables.group(ref,'team','amount'))
        excluded=self.tables.group(ref,'team','amount','exclude')
        self.assertEqual(excluded['row_count'],3)
        self.assertEqual(excluded['provenance']['excluded_null_keys'],1)
        self.assertEqual(self.tables.summarize(grouped,'sum')['sum'],'0.9')

    def test_group_limit_and_invalid_config_never_save_partial_results(self):
        ref=self.tables.add('groups.csv','team,amount\na,1\nb,2\n',{'amount':'integer'})
        before=self.tables.list()
        for group,column,nulls,limit in [('team','amount','include',1),('missing','amount','include',100),('team','team','include',100),('team','amount','bad',100),('team','amount','include',True)]:
            with self.subTest(group=group,limit=limit),self.assertRaises(ValueError):
                self.tables.group(ref,group,column,nulls,limit)
        self.assertEqual(self.tables.list(),before)
        empty=self.tables.filter(ref,'amount','gt','100')
        self.assertEqual(self.tables.group(empty,'team','amount')['row_count'],0)

    def test_decimal_keys_group_by_numeric_equality(self):
        ref=self.tables.add('keys.csv','key,amount\n0.10,0.1\n0.1,0.2\n',{'key':'decimal','amount':'decimal'})
        result=self.tables.group(ref,'key','amount')
        self.assertEqual(result['row_count'],1)
        self.assertEqual(self.tables.read(result['id'])['rows'][0]['sum'],'0.3')

    def test_native_group_then_summary(self):
        ref=self.tables.add('teams.csv','team,amount\na,0.1\na,0.2\nb,0.4\n',{'amount':'decimal'})
        workflow={'format':'graphcore.studio.v1','nodes':[
            {'id':'start','type':'input'},
            {'id':'group','type':'data_group','config':{'input_field':'table','group_column':'team','column':'amount','output_key':'grouped'}},
            {'id':'summary','type':'data','config':{'input_field':'grouped','column':'sum','output_key':'stats'}},
            {'id':'end','type':'output','config':{'template':'{{stats.sum}}'}}],
            'edges':[{'source':'start','target':'group'},{'source':'group','target':'summary'},{'source':'summary','target':'end'}]}
        with compile_workflow(workflow,summarize=self.tables.summarize,group_table=self.tables.group) as graph:
            result=graph.invoke({'table':ref})
        self.assertEqual(result.state['output'],'0.7')
        self.assertNotIn('rows',result.state['grouped'])
        workflow['nodes'][1]['config']['max_groups']=501
        self.assertTrue(validate(workflow))

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
