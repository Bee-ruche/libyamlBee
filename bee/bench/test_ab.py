#!/usr/bin/env python3
"""Tests unitaires des calculs statistiques d'ab.py (test du signe, gain relatif).

Usage : python3 bee/bench/test_ab.py
"""

import importlib.util
import os
import unittest

_CHEMIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ab.py")
_SPEC = importlib.util.spec_from_file_location("ab", _CHEMIN)
ab = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ab)


class SeuilDuSigne(unittest.TestCase):
    def test_table_documentee(self):
        attendu = {6: 6, 7: 7, 8: 8, 9: 8, 10: 9, 11: 10, 12: 10, 13: 11, 14: 12, 15: 12, 16: 13, 17: 14, 18: 14, 19: 15, 20: 16}
        for n, k in attendu.items():
            self.assertEqual(ab.seuil_signe(n), k, f"N = {n}")

    def test_trop_peu_de_paires(self):
        for n in range(0, 6):
            self.assertIsNone(ab.seuil_signe(n), f"N = {n}")

    def test_p_valeur_n10_k9(self):
        self.assertAlmostEqual(ab.p_unilaterale(10, 9), 11 / 1024)


class TestDuSigne(unittest.TestCase):
    def test_toutes_egales_ni_gain_ni_degradation(self):
        r = ab.test_du_signe([3.5054] * 10, [3.5054] * 10, "plus_haut")
        self.assertEqual(r["egalites"], 10)
        self.assertEqual(r["paires_utiles"], 0)
        self.assertIsNone(r["seuil_k"])
        self.assertFalse(r["au_dela_du_bruit"])
        self.assertFalse(r["degradation_au_dela_du_bruit"])
        self.assertIsNone(r["p_amelioration"])

    def test_egalites_ecartees_avant_le_seuil(self):
        # 9 égalités et 1 paire gagnée par B (cas de memoire_max_ko) : N' = 1, aucune conclusion.
        r = ab.test_du_signe([1564] * 10, [1564] * 9 + [1548], "plus_bas")
        self.assertEqual((r["victoires_B"], r["victoires_A"], r["egalites"]), (1, 0, 9))
        self.assertFalse(r["au_dela_du_bruit"])
        # 4 égalités, 6 paires gagnées par B : N' = 6, k = 6, donc significatif.
        r = ab.test_du_signe([10] * 10, [10] * 4 + [11] * 6, "plus_haut")
        self.assertEqual(r["seuil_k"], 6)
        self.assertTrue(r["au_dela_du_bruit"])
        # 4 égalités, 5 gagnées par B et 1 par A : N' = 6, k = 6, pas significatif.
        r = ab.test_du_signe([10] * 10, [10] * 4 + [11] * 5 + [9], "plus_haut")
        self.assertFalse(r["au_dela_du_bruit"])
        self.assertFalse(r["degradation_au_dela_du_bruit"])

    def test_deterministe_qui_change(self):
        r = ab.test_du_signe([3.5054] * 10, [3.5100] * 10, "plus_haut")
        self.assertTrue(r["au_dela_du_bruit"])
        r = ab.test_du_signe([3.5054] * 10, [3.5000] * 10, "plus_haut")
        self.assertTrue(r["degradation_au_dela_du_bruit"])
        self.assertFalse(r["au_dela_du_bruit"])

    def test_sens_plus_bas(self):
        r = ab.test_du_signe([1600] * 10, [1500] * 10, "plus_bas")
        self.assertTrue(r["au_dela_du_bruit"])
        r = ab.test_du_signe([1500] * 10, [1600] * 10, "plus_bas")
        self.assertTrue(r["degradation_au_dela_du_bruit"])

    def test_neuf_sur_dix(self):
        a = [100.0] * 10
        b = [101.0] * 9 + [99.0]
        r = ab.test_du_signe(a, b, "plus_haut")
        self.assertEqual(r["seuil_k"], 9)
        self.assertTrue(r["au_dela_du_bruit"])
        b = [101.0] * 8 + [99.0] * 2
        self.assertFalse(ab.test_du_signe(a, b, "plus_haut")["au_dela_du_bruit"])

    def test_valeurs_absentes_ignorees(self):
        r = ab.test_du_signe([None] * 10, [None] * 10, "plus_haut")
        self.assertEqual(r["paires"], 0)
        self.assertFalse(r["au_dela_du_bruit"])


class GainRelatif(unittest.TestCase):
    def test_sens(self):
        self.assertAlmostEqual(ab.gain_relatif(100.0, 103.0, "plus_haut"), 0.03)
        self.assertAlmostEqual(ab.gain_relatif(1000.0, 970.0, "plus_bas"), 0.03)
        self.assertIsNone(ab.gain_relatif(0, 1.0, "plus_haut"))
        self.assertIsNone(ab.gain_relatif(None, 1.0, "plus_haut"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
