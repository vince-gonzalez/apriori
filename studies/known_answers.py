#!/usr/bin/env python3
"""
============================================================
Eleven references whose right answer is known
F-Keys | www.f-keys.com
------------------------------------------------------------
Six real papers, four references made up the way a chatbot
makes them (real names, real journals, invented titles), and
one real paper that has been retracted. Each carries the state
it must come back with. Exits 1 on any miss.

Before the 2026-09-29 fix this scored 9 of 11: "Attention Is
All You Need" was matched to a 2025 upload sharing its title,
and the retracted Wakefield paper lost its match to a letter
of the same title printed five months later.

  python studies/known_answers.py

Run from the repository root. Standard library only.
============================================================
"""
import sys

sys.path.insert(0, "src")

from authorecon import reference_check as rc  # noqa: E402

REAL = {rc.LOCATED, rc.CONFIRMED}
FLAGGED = {rc.UNLOCATABLE, rc.REVIEW, rc.DIVERGENT}
WITHDRAWN = {rc.RETRACTED}

CASES = [
    (REAL, "Shannon, C. E. (1948). A mathematical theory of communication. Bell System Technical Journal, 27(3), 379-423."),
    (REAL, "Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, L., & Polosukhin, I. (2017). Attention is all you need. Advances in Neural Information Processing Systems, 30."),
    (REAL, "He, K., Zhang, X., Ren, S., & Sun, J. (2016). Deep residual learning for image recognition. Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition, 770-778."),
    (REAL, "Kahneman, D., & Tversky, A. (1979). Prospect theory: An analysis of decision under risk. Econometrica, 47(2), 263-291."),
    (REAL, "Watson, J. D., & Crick, F. H. C. (1953). Molecular structure of nucleic acids: A structure for deoxyribose nucleic acid. Nature, 171(4356), 737-738."),
    (REAL, "LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553), 436-444."),
    (FLAGGED, "Merriweather, J. P., & Okonkwo, A. (2021). Recursive semantic drift in low-resource transformer alignment. Journal of Computational Semiotics, 14(2), 233-259."),
    (FLAGGED, "Thompson, R. L., & Nguyen, H. (2019). The impact of social media use on adolescent sleep quality: A longitudinal study. Journal of Adolescent Health, 64(3), 312-320."),
    (FLAGGED, "Hinton, G., & Bengio, Y. (2018). Neural pathways of curiosity-driven learning. Nature Neuroscience, 21(4), 512-520."),
    (FLAGGED, "Smith, J. A. (2020). Climate anxiety and consumer behavior in Gen Z: A mixed-methods analysis. Journal of Environmental Psychology, 72, 101512."),
    (WITHDRAWN, "Wakefield, A. J., Murch, S. H., Anthony, A., et al. (1998). Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children. The Lancet, 351(9103), 637-641."),
]


def main():
    misses = 0
    for want, ref in CASES:
        got = rc.check_one(ref)
        ok = got["state"] in want
        misses += 0 if ok else 1
        found = (got.get("found") or {}).get("doi") or "-"
        print("{}  {:<12} {}  {}".format("ok  " if ok else "MISS", got["state"],
                                          found, ref[:60]))
    print("{} of {} right".format(len(CASES) - misses, len(CASES)))
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main())
