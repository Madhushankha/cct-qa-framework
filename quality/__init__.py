"""P9 quality package — grade the chatbot's RESPONSE QUALITY (not correctness) from a
canonical Result's transcript. Deterministic layer (quality.checks) is stdlib-only and
network-free; the LLM judge layer (quality.rubric) is optional and only runs when a
caller explicitly opts in (quality.grade.quality_report(use_llm=True) or `cctqa quality --llm`).
"""
