"""Unit-Tests für evaluation/metrics.py und die ASR-Bewertung (ohne Modelle)."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation import metrics as M  # noqa: E402


def test_normalize_keeps_numbers_times_and_diacritics():
    assert M.normalize("Um 07:30 Uhr: 4,5 m³ Beton!") == "um 07:30 uhr 4.5 m³ beton"
    assert M.normalize("İşverenin firması, ŁÓDŹ.") == "işverenin firması łódź"
    assert M.normalize("am 20.11.2026") == "am 20.11.2026"


def test_wer_and_alignment():
    c = M.wer_counts("der bagger steht seit 10 uhr", "der bagger steht 10 uhr jetzt")
    assert (c["del"], c["ins"], c["sub"], c["n_ref"]) == (1, 1, 0, 6)
    assert M.wer_counts("a b", "a b")["errors"] == 0


def test_term_and_number_hits():
    hit, tot, missed = M.term_hits("Bewehrung in Achse C fehlt, Bewehrung", "Bewährung in Achse C fehlt",
                                   ["Bewehrung", "Achse C"])
    assert (hit, tot) == (1, 3) and missed == ["Bewehrung"]
    assert M.number_hits("14 Mann statt 16, ab 07:30", "14 Mann statt 60, ab 7:30") == (2, 3)


def test_hyp_word_correctness():
    words = [{"word": "Bagger", "score": 0.9}, {"word": "steht,", "score": 0.8}, {"word": "zeit", "score": 0.2}]
    assert M.hyp_word_correctness("Bagger steht seit", words) == [(0.9, True), (0.8, True), (0.2, False)]


def test_prf_macro_confusion():
    assert M.prf(2, 1, 1)["f1"] == 2 / 3
    pairs = [("a", "a"), ("a", "b"), ("b", "b")]
    assert abs(M.macro_f1(pairs) - (2 / 3 + 2 / 3) / 2) < 1e-9
    assert M.confusion(pairs)["a"] == {"a": 1, "b": 1}


def test_calibration():
    assert M.auroc([0.9, 0.8, 0.1], [True, True, False]) == 1.0
    assert M.auroc([0.5, 0.5], [True, False]) == 0.5
    assert M.ece([1.0, 1.0], [True, True]) == 0.0
    rc = M.risk_coverage([0.9, 0.5, 0.1], [True, True, False])
    assert rc["curve"][-1]["risk"] == 1 / 3 and rc["aurc"] < 1 / 3


def test_cluster_bootstrap_and_mcnemar():
    items = [{"scenario_id": s, "errors": e, "n_ref": 10} for s, e in [("A", 1), ("A", 1), ("B", 3), ("C", 0)]]
    r = M.cluster_bootstrap(items, M.ratio("errors", "n_ref"), n=500)
    assert r["value"] == 5 / 40 and r["lo"] <= r["value"] <= r["hi"] and r["n_clusters"] == 3
    assert M.mcnemar([True] * 10, [False] * 10)["p"] < 0.01
    assert M.mcnemar([True, False], [False, True])["p"] == 1.0
    assert math.isnan(M.cluster_bootstrap([{"id": 1, "x": 1}], M.mean_of("x"))["lo"])


def test_asr_item_scoring_and_summary():
    from evaluation import eval_asr as E

    man = [{"id": "s1_snr5", "file": "s1_snr5.wav", "text": "Der Bagger steht seit 10 Uhr", "scenario_id": "S1",
            "lang": "de", "snr_db": 5},
           {"id": "n1", "file": "n1.wav", "text": "", "scenario_id": "N", "snr_db": 0}]
    hyps = {"s1_snr5": {"text": "Der Bagger steht seit 11 Uhr", "language": "de", "duration": 3.0,
                        "segments": [{"words": [{"word": "Der", "score": .9}, {"word": "Bagger", "score": .9},
                                                {"word": "steht", "score": .9}, {"word": "seit", "score": .9},
                                                {"word": "11", "score": .3}, {"word": "Uhr", "score": .9}]}]},
            "n1": {"text": "Vielen Dank fürs Zuschauen", "language": "de", "duration": 60.0, "segments": []}}
    rows = [E.score(r, hyps[r["id"]], ["Bagger"]) for r in man]
    s = E.summarize(rows)
    assert s["overall"]["WER"]["value"] == 1 / 6
    assert s["overall"]["number_recall"]["value"] == 0.0 and s["overall"]["term_recall"]["value"] == 1.0
    assert s["hallucination"]["words_per_min"] == 4.0
    assert s["word_score_calibration"]["auroc_correct_vs_wrong"] == 1.0
    assert "| gesamt |" in E.to_markdown(s)
