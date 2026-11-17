"""Format an alert and its reason codes into a prompt for a language-model alert note.

Template only: nothing here calls an external API. If an API key is provided
later, the returned string is what would be sent. The prompt carries only the
masked card number and transaction facts, no personal data.
"""

REASON_GLOSSARY = {
    "HIGH_AMT": "the transaction amount is high",
    "AMT_": "the amount is a multiple of the card's average of its previous 30 transactions",
    "NO_CARD_HISTORY": "the card has no earlier transactions to compare with",
    "LATE_NIGHT": "the transaction happened between 22:00 and 03:59",
    "HOUR_": "the hour of day raised the score",
    "SPEND_24H_": "the card's spend in the last 24 hours is high",
    "VELOCITY_": "several transactions on the card in the last 60 minutes",
    "DISTANCE_": "distance between the cardholder's home and the merchant",
    "NEW_MERCHANT": "first transaction of this card at this merchant",
    "REPEAT_MERCHANT": "the card has used this merchant before",
    "RULES_FIRED_": "number of rules that fired on this transaction",
    "CAT_": "merchant category",
    "LATE_NIGHT_HIGH_VALUE": "rule R3 fired (late night, high value)",
    "RISKY_CATEGORY_AMT": "rule R4 fired (high amount in a high-risk category)",
    "SPEND_BURST_48H": "rule R7 fired (48-hour spend far above the card's normal)",
    "AMT_SPIKE_RULE": "retired rule R2 fired (amount spike against the card's average)",
    "NEW_MERCHANT_HIGH_AMT": "shadow rule R6 fired (high amount at a new merchant)",
    "DISTANCE_RULE": "retired rule R5 fired (far from home)",
    "VELOCITY_RULE": "retired rule R1 fired (velocity)",
}

TEMPLATE = """You are helping a card-fraud analyst triage an alert. Write a note of at most three
sentences that explains why this alert was ranked where it was, using only the facts below.
Do not decide whether it is fraud, do not suggest contacting anyone, and do not invent facts.

Alert
- Card: {card}
- Time: {time}
- Merchant category: {category}
- Amount: {amount}
- Rules that alerted: {rules}
- Model score (0 to 1, higher means review first): {score}

Top reasons from the model, most important first
{reasons}
"""


def describe(code):
    for prefix, meaning in REASON_GLOSSARY.items():
        if code == prefix or code.startswith(prefix):
            return meaning
    return "see the reason code"


def build_alert_note_prompt(alert, reason_codes):
    """alert: a mapping with card_id, ts, category, amt, active_rules, model_score."""
    reasons = "\n".join(f"- {code}: {describe(code)}" for code in reason_codes) or "- none above zero"
    return TEMPLATE.format(
        card="XXXX" + str(alert["card_id"])[-4:],
        time=f"{alert['ts']:%Y-%m-%d %H:%M}",
        category=alert["category"],
        amount=f"${alert['amt']:,.2f}",
        rules=alert["active_rules"],
        score=f"{alert['model_score']:.3f}",
        reasons=reasons,
    )
