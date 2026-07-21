import json
import unittest


from identify import (
    canonicalize_answer,
    empirical_distribution,
    js_divergence,
    parse_response_payload,
    rank_candidates,
)


class IdentifyCoreTests(unittest.TestCase):
    def test_canonicalize_and_reject_explanations(self):
        self.assertEqual(canonicalize_answer("  Heads!  ", "coin"), "h")
        self.assertEqual(canonicalize_answer("`Blue`.\n", "color"), "blue")
        self.assertIsNone(canonicalize_answer("The answer is 7", "num10"))
        self.assertIsNone(canonicalize_answer("", "word"))

    def test_empirical_distribution_ignores_invalid_values(self):
        dist, valid, invalid = empirical_distribution(
            ["7", "7", "5", "The answer is 7", ""] , "num10"
        )
        self.assertEqual(dist, {"7": 2 / 3, "5": 1 / 3})
        self.assertEqual((valid, invalid), (3, 2))

    def test_jsd_is_symmetric_and_bounded(self):
        p = {"a": 1.0}
        q = {"b": 1.0}
        self.assertAlmostEqual(js_divergence(p, q), js_divergence(q, p))
        self.assertAlmostEqual(js_divergence(p, p), 0.0)
        self.assertLessEqual(js_divergence(p, q), 1.0)

    def test_parse_responses_sse_and_json(self):
        sse = "\n".join(
            [
                'data: ' + json.dumps({"type": "response.output_text.done", "text": "OK"}),
                'data: ' + json.dumps({"type": "response.completed", "response": {"model": "gpt-test"}}),
                "data: [DONE]",
            ]
        )
        parsed = parse_response_payload(sse)
        self.assertEqual(parsed["text"], "OK")
        self.assertEqual(parsed["model"], "gpt-test")
        deltas = "\n".join(
            'data: ' + json.dumps({"type": "response.output_text.delta", "delta": part})
            for part in ("O", "K")
        )
        self.assertEqual(parse_response_payload(deltas)["text"], "OK")
        parsed_json = parse_response_payload(json.dumps({"model": "x", "output_text": "OK"}))
        self.assertEqual(parsed_json["text"], "OK")
        parsed_output = parse_response_payload(json.dumps({
            "model": "x",
            "output": [{"content": [{"type": "output_text", "text": "OK"}]}],
        }))
        self.assertEqual(parsed_output["text"], "OK")

    def test_rank_candidates_requires_common_probe_count(self):
        observed = {"p1": {"a": 1.0}, "p2": {"b": 1.0}}
        refs = {
            "model-a": {"p1": {"a": 1.0}, "p2": {"b": 1.0}},
            "model-b": {"p1": {"b": 1.0}, "p2": {"a": 1.0}},
        }
        ranked = rank_candidates(observed, refs, min_common=2)
        self.assertEqual(ranked[0]["model"], "model-a")
        self.assertAlmostEqual(ranked[0]["mean_jsd"], 0.0)
        self.assertEqual(rank_candidates(observed, {"x": {"p1": {"a": 1.0}}}, min_common=2), [])


if __name__ == "__main__":
    unittest.main()
