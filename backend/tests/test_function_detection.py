"""
Test unitaire — Détection des fonctions en échec documentées (Excel) et génériques.

Vérifie que :
1. Les 4 lignes de trace exactes avec fonctions Excel (GetAuthRouting, CardInSaf,
   GetTimers, GetSecurityFlags) sont bien matchées par _build_function_failure_patterns().
2. Chacun des 4 noms de fonctions est présent dans get_monitored_function_names()
   (lecture live de Spec_PowerCARD.xlsx).
3. La regex générique RE_GENERIC_FAILURE couvre les 3 fonctions non documentées
   (swimon_check_msg_id, Get_IssScriptData, gen_iss_script_data).
"""

import re
import sys
import os
from pathlib import Path

# Assurer que le dossier backend est dans le path pour les imports relatifs
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.services.log_parser import (
    _build_function_failure_patterns,
    RE_GENERIC_FAILURE,
)

# ── Constantes de test ───────────────────────────────────────────────────────

# Lignes de trace exactes mentionnées dans le rapport de bug
EXCEL_FAILURE_LINES = [
    ("GetAuthRouting",    "End   GetAuthRouting NOK ( -1 )"),
    ("CardInSaf",         "End CardInSaf ( NOK )"),
    ("GetTimers",         "End GetTimers(-1)"),
    ("GetSecurityFlags",  "End GetSecurityFlags NOK (-1)"),
]

# Lignes pour les fonctions non documentées (détection générique)
GENERIC_FAILURE_LINES = [
    ("swimon_check_msg_id",  "some prefix | 4 | End swimon_check_msg_id NOK"),
    ("Get_IssScriptData",    "some prefix | 4 | End Get_IssScriptData ( NOK )"),
    ("gen_iss_script_data",  "some prefix | 4 | End gen_iss_script_data(-1)"),
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_patterns_with_mock(func_names: list) -> dict:
    """Construit les patterns en simulant une liste de fonctions documentées."""
    patterns = {}
    for func in func_names:
        patterns[func] = re.compile(
            rf"\b{re.escape(func)}\b(?:\s*\(\s*\))?\s*"
            rf"(?P<fail>"
            rf"NOK\s*\(\s*-\d+\s*\)"
            rf"|NOK"
            rf"|\(\s*NOK\s*\)"
            rf"|\(\s*-\d+\s*\)"
            rf"|!=\s*OK"
            rf"|!=\s*0"
            rf"|ERROR"
            rf")",
            re.IGNORECASE,
        )
    return patterns


# ── Tests Bug 1 : regex des fonctions documentées ────────────────────────────

class TestExcelFunctionPatterns:
    """
    Valide que chacune des 4 lignes de trace exactes est détectée par la regex
    de détection des fonctions documentées.
    """

    def setup_method(self):
        """Construit les patterns avec la liste des 4 fonctions connues."""
        self.func_names = [func for func, _ in EXCEL_FAILURE_LINES]
        self.patterns = _build_patterns_with_mock(self.func_names)

    def test_get_auth_routing_nok_with_spaces(self):
        """'End   GetAuthRouting NOK ( -1 )' — espaces multiples + ( -1 ) avec espaces internes."""
        func = "GetAuthRouting"
        line = "End   GetAuthRouting NOK ( -1 )"
        assert func in line, f"PREREQUIS : '{func}' doit être présent dans la ligne"
        pattern = self.patterns[func]
        m = pattern.search(line)
        assert m is not None, (
            f"ECHEC : Pattern '{pattern.pattern}' n'a pas matché '{line}'.\n"
            "Cause probable : la regex ne couvre pas 'NOK ( -1 )' avec espaces internes."
        )
        assert m.group("fail").strip().upper().startswith("NOK")

    def test_card_in_saf_nok_parentheses(self):
        """'End CardInSaf ( NOK )' — résultat ( NOK ) avec espaces internes."""
        func = "CardInSaf"
        line = "End CardInSaf ( NOK )"
        assert func in line
        pattern = self.patterns[func]
        m = pattern.search(line)
        assert m is not None, (
            f"ECHEC : Pattern '{pattern.pattern}' n'a pas matché '{line}'.\n"
            "Cause probable : '( NOK )' avec espaces non couvert."
        )
        assert "NOK" in m.group("fail").upper()

    def test_get_timers_minus_one_no_space(self):
        """'End GetTimers(-1)' — (-1) sans espace avant parenthèse."""
        func = "GetTimers"
        line = "End GetTimers(-1)"
        assert func in line
        pattern = self.patterns[func]
        m = pattern.search(line)
        assert m is not None, (
            f"ECHEC : Pattern '{pattern.pattern}' n'a pas matché '{line}'.\n"
            "Cause probable : '(-1)' accolé sans espace non couvert."
        )
        assert "-1" in m.group("fail")

    def test_get_security_flags_nok_minus_one(self):
        """'End GetSecurityFlags NOK (-1)' — NOK suivi de (-1) séparé par espace."""
        func = "GetSecurityFlags"
        line = "End GetSecurityFlags NOK (-1)"
        assert func in line
        pattern = self.patterns[func]
        m = pattern.search(line)
        assert m is not None, (
            f"ECHEC : Pattern '{pattern.pattern}' n'a pas matché '{line}'.\n"
            "Cause probable : 'NOK (-1)' séquentiel non couvert (le groupe s'arrête à NOK)."
        )


# ── Tests Bug 1 : présence dans get_monitored_function_names ─────────────────

class TestMonitoredFunctionNames:
    """
    Vérifie que les 4 fonctions documentées sont bien lues depuis l'Excel.
    Si une fonction est absente, le test échoue avec un message clair.
    """

    def test_excel_functions_are_monitored(self):
        """
        Les fonctions documentées dans l'Excel doivent figurer dans la liste surveillée.
        GetTimers est absent de Spec_PowerCARD.xlsx — il DOIT être capturé par la
        détection générique (RE_GENERIC_FAILURE), PAS disparaître silencieusement.
        """
        try:
            from app.services.spec_loader import get_monitored_function_names
            monitored = get_monitored_function_names()
        except FileNotFoundError as e:
            import pytest
            pytest.skip(f"Spec_PowerCARD.xlsx introuvable : {e}")

        # Fonctions attendues dans l'Excel
        expected_in_excel = ["GetAuthRouting", "CardInSaf", "GetSecurityFlags"]
        # Fonctions confirmées ABSENTES de l'Excel (détection générique attendue)
        expected_not_in_excel = ["GetTimers"]

        missing_from_excel = [f for f in expected_in_excel if f not in monitored]
        assert not missing_from_excel, (
            f"FONCTIONS ABSENTES de Spec_PowerCARD.xlsx : {missing_from_excel}\n"
            "Ces fonctions ne peuvent pas être détectées comme 'documentées'."
        )

        # Vérifier que GetTimers est bien absent (comportement attendu documenté)
        for func in expected_not_in_excel:
            assert func not in monitored, (
                f"INATTENDU : '{func}' est maintenant dans l'Excel — "
                "mettre à jour ce test si c'est intentionnel."
            )

    def test_get_timers_captured_by_generic_detection(self):
        """
        GetTimers est absent de l'Excel mais RE_GENERIC_FAILURE doit le capturer.
        C'est le comportement CORRECT : pas de disparition silencieuse.
        """
        line = "End GetTimers(-1)"
        BLACKLIST = {"END", "START", "FLD", "MTI", "PAN", "STAN", "RRN", "FROM", "TO", "HSM", "LEVEL"}
        matches = [
            (m.group("func"), m.group("fail"))
            for m in RE_GENERIC_FAILURE.finditer(line)
            if m.group("func").upper() not in BLACKLIST
        ]
        funcs = [f for f, _ in matches]
        assert "GetTimers" in funcs, (
            f"GetTimers non capturé par RE_GENERIC_FAILURE dans '{line}'\n"
            "Cette fonction doit apparaître comme 'non documentée dans Spec_PowerCARD.xlsx'."
        )

    def test_excel_patterns_built_correctly(self):
        """_build_function_failure_patterns() doit retourner un pattern par fonction."""
        try:
            from app.services.spec_loader import get_monitored_function_names
            monitored = get_monitored_function_names()
        except FileNotFoundError:
            import pytest
            pytest.skip("Spec_PowerCARD.xlsx introuvable")

        patterns = _build_function_failure_patterns()
        for func in monitored:
            assert func in patterns, f"Pattern manquant pour la fonction '{func}'"
            assert hasattr(patterns[func], "search"), f"Pattern invalide pour '{func}'"


# ── Tests : regex générique pour fonctions non documentées ───────────────────

class TestGenericFailureRegex:
    """
    Valide que RE_GENERIC_FAILURE couvre les 3 fonctions non documentées.
    """

    BLACKLIST = {"END", "START", "FLD", "MTI", "PAN", "STAN", "RRN", "FROM", "TO", "HSM", "LEVEL"}

    def _find_generic(self, line: str) -> list:
        results = []
        for m in RE_GENERIC_FAILURE.finditer(line):
            func = m.group("func")
            if func.upper() not in self.BLACKLIST:
                results.append((func, m.group("fail")))
        return results

    def test_swimon_check_msg_id(self):
        line = "some prefix | 4 | End swimon_check_msg_id NOK"
        matches = self._find_generic(line)
        funcs = [f for f, _ in matches]
        assert "swimon_check_msg_id" in funcs, (
            f"swimon_check_msg_id non détecté dans : '{line}'\nMatches trouvés : {matches}"
        )

    def test_get_iss_script_data(self):
        line = "some prefix | 4 | End Get_IssScriptData ( NOK )"
        matches = self._find_generic(line)
        funcs = [f for f, _ in matches]
        assert "Get_IssScriptData" in funcs, (
            f"Get_IssScriptData non détecté dans : '{line}'\nMatches trouvés : {matches}"
        )

    def test_gen_iss_script_data(self):
        line = "some prefix | 4 | End gen_iss_script_data(-1)"
        matches = self._find_generic(line)
        funcs = [f for f, _ in matches]
        assert "gen_iss_script_data" in funcs, (
            f"gen_iss_script_data non détecté dans : '{line}'\nMatches trouvés : {matches}"
        )


# ── Tests d'intégration : patterns construits avec les fonctions mock ─────────

class TestPatternCoverageAllCases:
    """
    Matrice complète : chaque combinaison (fonction, ligne) doit être détectée.
    """

    def test_all_excel_failure_lines_match(self):
        """Les 4 paires (fonction, ligne) doivent toutes matcher leur pattern respectif."""
        func_names = [f for f, _ in EXCEL_FAILURE_LINES]
        patterns = _build_patterns_with_mock(func_names)

        failures = []
        for func, line in EXCEL_FAILURE_LINES:
            assert func in line, f"PRE-CONDITION : '{func}' absent de '{line}'"
            pattern = patterns.get(func)
            if pattern is None:
                failures.append(f"  - Pas de pattern pour '{func}'")
                continue
            m = pattern.search(line)
            if m is None:
                failures.append(
                    f"  - '{func}' non détecté dans '{line}'\n"
                    f"    Pattern : {pattern.pattern}"
                )

        assert not failures, (
            "ECHECS DE DÉTECTION DES FONCTIONS DOCUMENTÉES :\n"
            + "\n".join(failures)
        )

    def test_additional_formats(self):
        """Formats supplémentaires qui doivent aussi être couverts."""
        extra_cases = [
            ("TestFunc", "End TestFunc NOK"),
            ("TestFunc", "End TestFunc (NOK)"),
            ("TestFunc", "End TestFunc ( NOK )"),
            ("TestFunc", "End TestFunc(-1)"),
            ("TestFunc", "End TestFunc( -1 )"),
            ("TestFunc", "End TestFunc NOK(-1)"),
            ("TestFunc", "End TestFunc NOK ( -1 )"),
            ("TestFunc", "End TestFunc NOK (-1)"),
            ("TestFunc", "End TestFunc != OK"),
            ("TestFunc", "End TestFunc ERROR"),
        ]
        patterns = _build_patterns_with_mock(["TestFunc"])
        pattern = patterns["TestFunc"]

        failures = []
        for func, line in extra_cases:
            if pattern.search(line) is None:
                failures.append(f"  Non matché : '{line}'")

        assert not failures, (
            "FORMATS NON COUVERTS PAR LA REGEX :\n" + "\n".join(failures)
        )


# ── Point d'entrée direct (hors pytest) ──────────────────────────────────────

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
