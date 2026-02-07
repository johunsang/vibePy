import unittest

from vibeweb.actions import execute_action
from vibeweb.spec import (
    ActionSpec,
    FlowActionSpec,
    FlowStepSpec,
    HttpActionSpec,
    ValueActionSpec,
)


class TestFlow(unittest.TestCase):
    def test_flow_on_error_continue_and_fallback(self) -> None:
        bad_http = ActionSpec(
            name="bad_http",
            kind="http",
            auth="api",
            http=HttpActionSpec(url="notaurl"),
        )
        fallback = ActionSpec(
            name="fallback",
            kind="value",
            auth="api",
            value=ValueActionSpec(data={"fallback": True}, status=200, ok=True),
        )
        workflow = ActionSpec(
            name="workflow",
            kind="flow",
            auth="api",
            flow=FlowActionSpec(
                steps=[
                    FlowStepSpec(id="try", use="bad_http", on_error="continue"),
                    FlowStepSpec(id="fb", use="fallback", when={"steps.try.ok": False}),
                ],
                return_step="fb",
            ),
        )
        registry = {"bad_http": bad_http, "fallback": fallback, "workflow": workflow}
        result = execute_action(workflow, input_data={"hello": "world"}, extra={"actions": registry})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"fallback": True})

    def test_flow_set_vars(self) -> None:
        make_value = ActionSpec(
            name="make_value",
            kind="value",
            auth="api",
            value=ValueActionSpec(data={"answer": 42}, status=200, ok=True),
        )
        read_vars = ActionSpec(
            name="read_vars",
            kind="value",
            auth="api",
            value=ValueActionSpec(data={"seen": "${vars.answer}"}, status=200, ok=True),
        )
        workflow = ActionSpec(
            name="workflow",
            kind="flow",
            auth="api",
            flow=FlowActionSpec(
                steps=[
                    FlowStepSpec(id="a", use="make_value", set={"answer": "${steps.a.data.answer}"}),
                    FlowStepSpec(id="b", use="read_vars", when={"$exists": "vars.answer"}),
                ],
                return_step="b",
            ),
        )
        registry = {"make_value": make_value, "read_vars": read_vars, "workflow": workflow}
        result = execute_action(workflow, input_data={}, extra={"actions": registry})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"seen": 42})


if __name__ == "__main__":
    unittest.main()
