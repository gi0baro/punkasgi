{{
    def fmt_ms(v):
        return f"{round(v, 3)}ms" if v else "N/A"

    def fmt_us(v):
        return f"{round(v, 1)}µs" if v else "N/A"

    def fmt_pct(v):
        return f"{round(v)}%" if v else "N/A"

    def fmt_mb(kb):
        return f"{round(kb / 1024, 1)}MB" if kb else "N/A"
}}
