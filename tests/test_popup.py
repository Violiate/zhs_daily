import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zhsgo.logger import setup as setup_logging
from zhsgo.util import stderr_safe
from zhsgo.ai import Answerer, PopupSolver
from zhsgo.ai.prompts import AnswerContext

stderr_safe()
setup_logging(log_dir=None, to_console=False)


class FakeBackend:
    def __init__(self, text): self.text = text
    def complete(self, prompt): return self.text


def q(qtype, options=None, content="题干"):
    return {"questionId": 1, "questionType": qtype, "content": content,
            "questionOptions": options or []}


def opt(i, content, result=""):
    return {"id": i, "content": content, "result": result}


def test_marked_single():
    solver = PopupSolver(Answerer(None), AnswerContext())
    assert solver.solve(q(1, [opt(11, "A", "1"), opt(12, "B")])) == "11"


def test_marked_fill_uses_content():
    solver = PopupSolver(Answerer(None), AnswerContext())
    assert solver.solve(q(3, [opt(11, "光合作用", "1"), opt(12, "呼吸作用")])) == "光合作用"


def test_unmarked_fill_ai():
    solver = PopupSolver(Answerer(FakeBackend("```answer\n引力\n```")), AnswerContext())
    assert solver.solve(q(3, content="苹果落地是因为什么？")) == "引力"


def test_unmarked_multiple_ai():
    text = '```answer\n[{"id": 11}, {"id": 12}]\n```'
    solver = PopupSolver(Answerer(FakeBackend(text)), AnswerContext())
    assert solver.solve(q(2, [opt(11, "A"), opt(12, "B")])) == "11,12"


def test_answer_right_fill():
    solver = PopupSolver(Answerer(None), AnswerContext())
    item = q(3, content="水的化学式")
    item["answerRight"] = "H2O"
    assert solver.solve(item) == "H2O"


def test_answer_right_choice_maps_to_id():
    solver = PopupSolver(Answerer(None), AnswerContext())
    item = q(1, [opt(11, "A"), opt(12, "B")])
    item["answerRight"] = "B"
    assert solver.solve(item) == "12"


def test_question_type_dict():
    solver = PopupSolver(Answerer(None), AnswerContext())
    item = q(1, [opt(11, "对", result="1"), opt(12, "错")])
    item["questionType"] = {"id": 14, "name": "判断题", "inputType": "radio"}
    item["name"] = "Python 支持函数式编程。"
    assert solver.solve(item) == "11"


def test_no_backend_fallback():
    solver = PopupSolver(Answerer(None), AnswerContext())
    assert solver.solve(q(1, [opt(11, "A"), opt(12, "B")])) == "11"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("[ok]", name)
    print("ALL PASS")
