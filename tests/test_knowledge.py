import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "python"))

from graphcore import END
from studio.engine import compile_workflow, validate
from studio.knowledge import KnowledgeError, LocalKnowledge


class KnowledgeTests(unittest.TestCase):
    def test_local_add_list_search_and_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            library = LocalKnowledge(directory)
            added = library.add("warehouse-policy.md", """# Delivery policy

North warehouse orders should arrive within two business days. Escalate delays.

# Payroll

Payroll records are retained for seven years.
""")
            self.assertEqual(library.list()[0]["name"], "warehouse-policy.md")
            result = library.search("north warehouse delivery delay", top_k=1)
            self.assertEqual(result["results"][0]["source"], "warehouse-policy.md")
            self.assertIn("two business days", result["results"][0]["text"])
            self.assertEqual(result["results"][0]["source_id"], added["id"])
            library.remove(added["id"])
            self.assertEqual(library.list(), [])
            self.assertEqual(library.search("warehouse delivery")["results"], [])

    def test_rejects_unsupported_or_empty_documents_and_empty_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            library = LocalKnowledge(directory)
            for name, text in (("manual.pdf", "text"), ("empty.txt", " ")):
                with self.subTest(name=name), self.assertRaises(KnowledgeError):
                    library.add(name, text)
            with self.assertRaises(KnowledgeError):
                library.search("  ")

    def test_retrieval_node_runs_through_native_graph_and_exposes_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            library = LocalKnowledge(directory)
            doc = library.add("guide.txt", "Returns are accepted within thirty days with a receipt.")
            workflow = {
                "format": "graphcore.studio.v1",
                "id": "document_lookup",
                "name": "Document lookup",
                "inputs": {"input": "What is the returns policy?"},
                "nodes": [
                    {"id": "start", "type": "input", "config": {}},
                    {"id": "lookup", "type": "retrieve", "config": {
                        "input_field": "input", "top_k": 2, "output_key": "context"}},
                    {"id": "finish", "type": "output", "config": {
                        "template": "{{context.results}}"}},
                ],
                "edges": [
                    {"source": "start", "target": "lookup"},
                    {"source": "lookup", "target": "finish"},
                ],
            }
            self.assertEqual(validate(workflow), [])
            with compile_workflow(workflow, retrieve=lambda _library, query, top_k:
                                   library.search(query, top_k)) as graph:
                result = graph.invoke(workflow["inputs"])
            self.assertEqual(result.state["context"]["results"][0]["source_id"], doc["id"])
            self.assertIn("thirty days", result.state["output"])


if __name__ == "__main__":
    unittest.main()
