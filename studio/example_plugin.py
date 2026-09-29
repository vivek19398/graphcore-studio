"""Launch with: python3 run_studio.py --plugin studio/example_plugin.py"""
def register(add_tool):
    # Import third-party libraries here, from the server's virtual environment.
    def sentence_count(value, config):
        import re
        sentences = [s.strip() for s in re.split(r"[.!?]+", str(value)) if s.strip()]
        return {"sentences": len(sentences), "items": sentences}
    add_tool("sentence_count", sentence_count, "Count sentences with a registered Python function")
