import sys
import unittest

import ollama_agents


class ToolingTests(unittest.TestCase):
    def test_build_tools_include_shell_url_and_file_ops_tools(self):
        tools = ollama_agents.build_tools(enable_rag=False, enable_file_tools=True)
        names = [tool.get("function", {}).get("name") for tool in tools]
        self.assertIn("run_command", names)
        self.assertIn("fetch_url", names)
        self.assertIn("list_dir", names)
        self.assertIn("repair_self", names)

    def test_run_command_executes_simple_command(self):
        result = ollama_agents.dispatch_tool_call(
            "run_command",
            {"command": [sys.executable, "-c", "print('ok')"]},
            {},
        )
        self.assertIn("ok", result)

    def test_extract_tool_calls_parses_repair_self_block(self):
        text = """REPAIR_SELF: tests/test_tooling.py
old text
---
new text
END_REPAIR_SELF"""
        calls = ollama_agents.extract_tool_calls(text)
        self.assertEqual(calls[0][0], "repair_self")
        self.assertEqual(calls[0][1]["path"], "tests/test_tooling.py")
        self.assertEqual(calls[0][1]["old_string"], "old text")
        self.assertEqual(calls[0][1]["new_string"], "new text")

    def test_resolve_rag_paths_uses_current_directory_by_default(self):
        paths = ollama_agents.resolve_rag_paths([], no_rag=False, cwd="/tmp/project")
        self.assertEqual(paths, ["/tmp/project"])


if __name__ == "__main__":
    unittest.main()
