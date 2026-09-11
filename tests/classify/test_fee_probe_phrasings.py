"""Contingency phrasings measured in the live probe (11 Sep 2026).

29 of 150 "unknown" personal-injury firms stated contingency plainly, in words the
spec's three P6 patterns missed. Each positive case below is a real sentence from a
real firm's site; each negative is a trap the patterns must not fire on.
"""

import pytest

from lge.classify.fee import detect_fee_model


@pytest.mark.parametrize(
    "sentence",
    [
        "You won’t pay anything unless you win",                      # mabreyfirm.com
        "You won�t pay anything unless you win",                      # same, mis-decoded page
        "No Fees Unless We Win",  # tkklaw.com, aleemlaw.com
        "We provide services on contingency, and you will not owe us anything unless we secure "
        "compensation for you",                                            # tkklaw.com
        "We don't get paid unless you are paid for your injuries",         # nylawyercaraccident.com
        "You don’t owe us a thing unless we win your case",           # kainelaw.com
        "Our team handles all our personal injury cases on a contingency basis",  # townesdavis.com
        "Since we charge no legal fees, unless and until we succeed",      # willenslaw.com
        "You will receive a free consultation, and no payment is required unless you win "
        "your lawsuit",                                                    # briskmanandbriskman.com
    ],
)
def test_real_contingency_phrasings_are_detected(sentence):
    assert detect_fee_model([(sentence, 5.0)]).value == "contingency"


@pytest.mark.parametrize(
    "sentence",
    [
        "Schedule a free consultation today",            # every fee model offers one
        "Your compensation will be reduced by your percentage of fault",
        "We accept Visa and all major cards",
        "Contingency plans for emergencies",
    ],
)
def test_traps_stay_unknown(sentence):
    assert detect_fee_model([(sentence, 5.0)]).value == "unknown"
