"""Example specs shown as one-click presets. Plain, realistic tickets — no hints about the ambiguity."""

PRESETS = [
    {
        "id": "split_bill",
        "title": "Split the bill",
        "tagline": "Money that doesn't divide evenly",
        "spec": "Split a restaurant bill evenly among n people. Return how much each person pays, rounded to cents.",
    },
    {
        "id": "business_days",
        "title": "Business days",
        "tagline": "Counting is harder than it looks",
        "spec": "Given a start date and an end date (ISO strings), return the number of business days between them.",
    },
    {
        "id": "dedupe_emails",
        "title": "Dedupe emails",
        "tagline": "Which duplicate wins?",
        "spec": "Remove duplicate email addresses from a list. Email comparison should be case-insensitive.",
    },
    {
        "id": "round_grade",
        "title": "Letter grade",
        "tagline": "Boundaries and rounding",
        "spec": "Convert a numeric exam score (0-100) to a letter grade: A is 90 and above, B is 80s, C is 70s, D is 60s, otherwise F. Scores can have decimals.",
    },
    {
        "id": "truncate",
        "title": "Truncate text",
        "tagline": "Does the ellipsis count?",
        "spec": "Truncate a string to at most max_len characters, adding '...' at the end if it was shortened.",
    },
    {
        "id": "percent_change",
        "title": "Percent change",
        "tagline": "From zero to anything",
        "spec": "Return the percentage change from an old value to a new value, rounded to one decimal place.",
    },
]
