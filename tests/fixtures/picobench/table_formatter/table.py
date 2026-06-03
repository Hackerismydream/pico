def render_table(headers, rows):
    return "\n".join(",".join(map(str, row)) for row in [headers, *rows])
