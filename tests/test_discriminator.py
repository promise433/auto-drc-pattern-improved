from __future__ import annotations

import unittest

from autodrc.discriminator import DiscriminatorWeights, score_case


class DiscriminatorTests(unittest.TestCase):
    def test_score_prefers_more_target_hits(self) -> None:
        w = DiscriminatorWeights(target_hit=2.0, non_target_penalty=0.2, delta_penalty=0.01)
        a = score_case(target_hits=1, total_hits=1, geometry_valid=True, delta_nm=20, weights=w)
        b = score_case(target_hits=2, total_hits=2, geometry_valid=True, delta_nm=20, weights=w)
        self.assertGreater(b.score, a.score)

    def test_invalid_penalty(self) -> None:
        w = DiscriminatorWeights(invalid_penalty=5.0)
        a = score_case(target_hits=1, total_hits=1, geometry_valid=True, delta_nm=20, weights=w)
        b = score_case(target_hits=1, total_hits=1, geometry_valid=False, delta_nm=20, weights=w)
        self.assertGreater(a.score, b.score)


if __name__ == "__main__":
    unittest.main()
