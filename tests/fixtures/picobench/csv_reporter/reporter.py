def summarize_amounts(rows):
    return sum(int(row["amount"]) for row in rows)
