from agent6_engine import eval_scope as E

def test_gold_label_ziele():
    assert E.gold_label("✓ In-Scope") == "ZIEL"
    assert E.gold_label("No Can") == "ZIEL"

def test_gold_label_kein():
    assert E.gold_label("Funksteuerung") == "KEIN"
    assert E.gold_label("⌀ Kein Objekt / unbrauchbar") == "KEIN"
    assert E.gold_label("Autonomous") == "KEIN"

def test_gold_label_ignore():
    assert E.gold_label("~ Unsicher") is None
    assert E.gold_label("") is None
    assert E.gold_label(None) is None

def test_pred_label():
    assert E.pred_label("In-Scope") == "ZIEL"
    assert E.pred_label("Out-of-Scope") == "KEIN"
    assert E.pred_label("Unsicher") == "KEIN"
    assert E.pred_label(None) == "KEIN"

def test_score_math():
    pairs = [
        ("No Can", "Out-of-Scope"),   # ZIEL verworfen -> FN
        ("In-Scope", "In-Scope"),     # TP
        ("Funksteuerung", "In-Scope"),# KEIN als ZIEL -> FP
        ("Funksteuerung", "Out-of-Scope"), # TN
        ("Unsicher", "In-Scope"),     # ignoriert
    ]
    m = E.score(pairs)
    assert m["tp"] == 1 and m["fn"] == 1 and m["fp"] == 1 and m["tn"] == 1
    assert m["ignoriert"] == 1 and m["ziele"] == 2
    assert abs(m["recall"] - 0.5) < 1e-9
    assert abs(m["precision"] - 0.5) < 1e-9
