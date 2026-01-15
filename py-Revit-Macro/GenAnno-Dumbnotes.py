def _score_strict_label_candidate(e):
    pn = _param_names_lower(e)
    # Relaxed requirements - just need some text-like params
    text_params = {"label", "id", "text", "value", "sample text"}
    if not any(tp in pn for tp in text_params):
        return 0
    return 260
