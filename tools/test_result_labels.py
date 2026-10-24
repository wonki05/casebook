"""Regression tests for outcome labels inferred only from the operative order."""
import copy
import unittest

from build_data import derive_result


def fetched(text, heading="【전문】"):
    return {"sections": [{"heading": heading, "text": text}]}


class DeriveResultTests(unittest.TestCase):
    def test_embedded_bracket_shapes(self):
        for left, right in (("【", "】"), ("〖", "〗"), ("[", "]")):
            with self.subTest(left=left):
                text = f"{left}원심판결{right} 서울고등법원 판결\n{left}주 문{right}\n상고를 기각한다.\n{left}이 유{right} 원심을 파기환송한 종전 판결."
                self.assertEqual(derive_result(fetched(text), {}), "상고기각")

    def test_plain_standalone_heading(self):
        text = "원심판결 | 서울고등법원\n\n주 문\n\n상고를 기각한다. 상고비용은 피고의 부담으로 한다.\n\n이 유\n파기환송한 참조판례"
        self.assertEqual(derive_result(fetched(text), {}), "상고기각")

    def test_separate_order_section(self):
        self.assertEqual(derive_result(fetched("원심판결을 파기하고 사건을 환송한다.", "【주 문】"), {}), "파기환송")

    def test_separate_ornate_order_section(self):
        self.assertEqual(derive_result(fetched("상고를 기각한다.", "〖주 문〗"), {}), "상고기각")

    def test_old_each_appeal_dismissed(self):
        self.assertEqual(derive_result(fetched("상고를 각 기각한다.", "[주문]"), {}), "상고기각")

    def test_all_appeals_dismissed(self):
        self.assertEqual(derive_result(fetched("상고를 모두 기각한다.", "[주문]"), {}), "상고기각")

    def test_spaced_old_type(self):
        self.assertEqual(derive_result(fetched("상 고 를 각 기 각 한 다.", "[주문]"), {}), "상고기각")

    def test_mixed_dispositions(self):
        order = ("원심판결 중 반소에 관한 원고(반소피고) 패소 부분을 파기하여 이 부분 사건을 청주지방법원에 환송하고, "
                 "그 부분에 대한 피고(반소원고)의 상고를 각하한다.\n피고(반소원고)의 나머지 상고를 기각한다.")
        self.assertEqual(derive_result(fetched(order, "[주문]"), {}), "파기환송·상고각하·상고기각")

    def test_registry_override(self):
        self.assertEqual(derive_result(fetched("상고를 기각한다.", "[주문]"), {"result": "일부 파기환송"}), "일부 파기환송")
        self.assertEqual(derive_result(None, {"outcome": "상고기각"}), "상고기각")

    def test_no_result_from_reasons_section(self):
        self.assertEqual(derive_result(fetched("원심판결을 파기하여 환송한다는 취지이다.", "[이유]"), {}), "")

    def test_no_result_from_reference_section(self):
        self.assertEqual(derive_result(fetched("[주문]\n상고를 기각한다.", "[참조판례]"), {}), "")

    def test_no_result_from_quoted_order_after_reason_heading(self):
        self.assertEqual(derive_result(fetched("[이유]\n참조판례의 인용:\n[주문]\n상고를 기각한다."), {}), "")

    def test_word_inside_sentence_is_not_heading(self):
        self.assertEqual(derive_result(fetched("원심판결 주문은 다음과 같다. 상고를 기각한다."), {}), "")

    def test_stop_before_next_heading(self):
        text = "[주문]\n상고를 기각한다.\n[별지]\n원심판결을 파기하고 환송한다."
        self.assertEqual(derive_result(fetched(text), {}), "상고기각")

    def test_existing_constitutional_labels(self):
        self.assertEqual(derive_result(fetched("이 조항은 헌법에 위반되지 아니한다.", "[주문]"), {}), "합헌")
        self.assertEqual(derive_result(fetched("이 조항은 헌법에 합치되지 아니한다. 나머지 청구는 기각한다.", "[주문]"), {}), "헌법불합치·기각")

    def test_missing_order_stays_unknown(self):
        self.assertEqual(derive_result(fetched("[원심판결]\n서울고등법원 판결"), {}), "")
        self.assertEqual(derive_result(None, {}), "")

    def test_numbered_order_items_are_not_section_headings(self):
        order = "[1] 이 조항은 헌법에 위반된다.\n[2] 나머지 청구는 기각한다."
        for heading in ("[주문]", "【전문】"):
            with self.subTest(heading=heading):
                text = order if heading == "[주문]" else "[주문]\n" + order + "\n[이유]\n파기환송한 판례"
                self.assertEqual(derive_result(fetched(text, heading), {}), "위헌·기각")

    def test_inline_statute_brackets_in_order_are_preserved(self):
        text = "[주문]\n[민법] 이 조항은 헌법에 위반되지 아니한다.\n[이유]\n기각한 원심판결"
        self.assertEqual(derive_result(fetched(text), {}), "합헌")

    def test_source_untouched(self):
        source = fetched("주 문\n상고를 각 기각한다.\n이 유\n▒▒▒")
        before = copy.deepcopy(source)
        derive_result(source, {})
        self.assertEqual(source, before)


if __name__ == "__main__":
    unittest.main()

