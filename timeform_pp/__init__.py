"""TimeformUS past-performance reader (text layer of the TimeformUS PP PDF).  Its values live under their own
namespace (`timeform`) and are never substituted for Brisnet values or the reverse."""
from .reader import parse_lines, parse_pdf, parse_source, identity, rank_by_top_fig, merge_timeform   # noqa: F401
