import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from graphcore import Graph, GraphCoreError, Update, Interrupt, END

class Tests(unittest.TestCase):
    def graph(self, fn, **kwargs):
        g = Graph(**kwargs)
        g.add_node("a", fn).set_entry("a").add_edge("a", END)
        self.addCleanup(g.close)
        return g

    def test_nested_state(self):
        value = {"nested": [1, True, None, "世界\n\0"]}
        g = self.graph(lambda s, c: {"output": s["input"]})
        self.assertEqual(g.invoke({"input": value}).state["output"], value)

    def test_branch(self):
        with Graph() as g:
            g.add_node("a", lambda s, c: Update(next="b"))
            g.add_node("b", lambda s, c: {"ok": True})
            g.set_entry("a").add_edge("a", END).add_edge("a", "b").add_edge("b", END)
            self.assertTrue(g.invoke().state["ok"])

    def test_exception(self):
        def bad(s, c):
            raise ValueError("library failed")
        g = self.graph(bad)
        with self.assertRaisesRegex(GraphCoreError, "ValueError: library failed"):
            g.invoke()

    def test_resume_new_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "run.chk")
            g = self.graph(lambda s, c: {"answer": c.response} if c.resumed else Interrupt("approve?"))
            self.assertTrue(g.invoke(checkpoint=path).suspended)
            script = '''from graphcore import Graph, END
with Graph() as g:
    g.add_node("a", lambda s,c: {"answer": c.response}).set_entry("a").add_edge("a",END)
    assert g.resume(__import__("sys").argv[1], response="yes").state["answer"] == "yes"
'''
            subprocess.run([sys.executable, "-c", script, path], check=True)
            self.assertEqual(g.recover(path).state["answer"], "yes")

    def test_crash_recovery_does_not_repeat_committed_node(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "crash.chk")
            script = """import os, sys
from graphcore import Graph, END
with Graph() as g:
    g.add_node("first", lambda s,c: {"committed": 42})
    g.add_node("crash", lambda s,c: os._exit(23))
    g.set_entry("first").add_edge("first", "crash").add_edge("crash", END)
    g.invoke(checkpoint=sys.argv[1])
"""
            process = subprocess.run([sys.executable, "-c", script, path])
            self.assertEqual(process.returncode, 23)
            with Graph() as g:
                def forbidden(s, c):
                    raise AssertionError("committed node executed again")
                g.add_node("first", forbidden).add_node("crash", lambda s,c: {"done": True})
                g.set_entry("first").add_edge("first", "crash").add_edge("crash", END)
                result = g.recover(path)
                self.assertEqual(result.state, {"committed": 42, "done": True})
                self.assertEqual(result.steps, 2)

    def test_cancelled_waiter_keeps_run_owned(self):
        async def run():
            gate = asyncio.Event()
            entered = asyncio.Event()
            async def node(s, c):
                entered.set()
                await gate.wait()
                return {"done": True}
            with Graph() as g:
                g.add_node("a", node).set_entry("a").add_edge("a", END)
                task = asyncio.create_task(g.ainvoke())
                await entered.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                with self.assertRaisesRegex(GraphCoreError, "in use"):
                    g.close()
                gate.set()
                for _ in range(100):
                    if not g._lock.locked():
                        break
                    await asyncio.sleep(0.01)
                self.assertFalse(g._lock.locked())
        asyncio.run(run())

    def test_async(self):
        async def node(s, c):
            await asyncio.sleep(0.01)
            return {"ok": asyncio.get_running_loop() is loop}
        g = self.graph(node)
        async def run():
            nonlocal loop
            loop = asyncio.get_running_loop()
            self.assertTrue((await g.ainvoke()).state["ok"])
            self.assertTrue((await g.ainvoke()).state["ok"])
        loop = None
        asyncio.run(run())
        with self.assertRaisesRegex(GraphCoreError, "Async callbacks"):
            g.invoke()

    def test_reentrant_rejected(self):
        g = self.graph(lambda s, c: g.invoke())
        with self.assertRaisesRegex(GraphCoreError, "Graph is in use"):
            g.invoke()

    def test_closed(self):
        g = self.graph(lambda s, c: {})
        g.close()
        with self.assertRaisesRegex(GraphCoreError, "closed"):
            g.invoke()

    def test_invalid_state(self):
        g = self.graph(lambda s, c: {})
        with self.assertRaises(ValueError):
            g.invoke({"x": float("nan")})
        self.assertEqual(g.invoke().state, {})

if __name__ == "__main__":
    unittest.main()
