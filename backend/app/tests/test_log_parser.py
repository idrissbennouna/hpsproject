import unittest
import tempfile
import os
import uuid
import random
import string
from pathlib import Path

from app.services.log_parser import (
    parse_trace_file,
    parse_and_format_log_file,
    get_iso_field_info,
    get_mti_info,
)


class TestLogParser(unittest.TestCase):
    def setUp(self):
        self.temp_files = []

    def tearDown(self):
        for path in self.temp_files:
            if os.path.exists(path):
                os.remove(path)

    def _create_temp_log(self, content: str) -> str:
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".TRC") as f:
            f.write(content)
            path = f.name
        self.temp_files.append(path)
        return path

    def test_iso8583_reference_lookup(self):
        """Vérifie que le référentiel JSON ISO 8583 charge correctement les métadonnées de champs et de MTI."""
        info_011 = get_iso_field_info("011")
        self.assertIsNotNone(info_011)
        self.assertEqual(info_011["name"], "STAN")

        info_002 = get_iso_field_info("002")
        self.assertIsNotNone(info_002)
        self.assertEqual(info_002["name"], "PAN")

        mti_desc = get_mti_info("1100")
        self.assertIn("Authorization Request", mti_desc)

    def test_full_vs_compact_mode_behavior(self):
        """
        Vérifie que :
        - Le mode 'full' capture toutes les lignes, y compris les lignes génériques inconnues.
        - Le mode 'compact' ne garde que les événements enrichis et structurés, réduisant la taille du texte.
        """
        random_token = f"DEBUG_TRACE_UNSTRUCTURED_{uuid.uuid4().hex[:8]}"
        session_id = "SESS_TEST_MODES_101"

        log_content = (
            f"2026-07-28 10:00:00.100 0001 {session_id}|4| - M.T.I : [1100]\n"
            f"2026-07-28 10:00:00.101 0001 {session_id}|4| INTERNAL STAN}} 6 000123\n"
            f"2026-07-28 10:00:00.102 0001 {session_id}|4| {random_token}\n"
            f"2026-07-28 10:00:00.103 0001 {session_id}|4| - FLD (037) : (12) : [987654321012]\n"
            f"2026-07-28 10:00:00.104 0001 {session_id}|4| HsmResultCode = 00\n"
        )
        file_path = self._create_temp_log(log_content)

        full_output = parse_and_format_log_file(file_path, mode="full")
        compact_output = parse_and_format_log_file(file_path, mode="compact")

        # Mode FULL doit contenir la ligne arbitraire non enrichie
        self.assertIn(random_token, full_output)

        # Mode COMPACT doit exclure la ligne non enrichie
        self.assertNotIn(random_token, compact_output)

        # Les deux modes doivent contenir la synthèse globale et les marqueurs structurés
        self.assertIn("=== SYNTHÈSE GLOBALE DE LA TRACE ===", full_output)
        self.assertIn("=== SYNTHÈSE GLOBALE DE LA TRACE ===", compact_output)
        self.assertIn("987654321012", compact_output)

    def test_global_summary_header(self):
        """Vérifie la génération du bloc de synthèse globale au début du formatage."""
        session_id = "SESS_SUMMARY_202"
        log_content = (
            f"2026-07-28 11:00:00.000 0002 {session_id}|4| - M.T.I : [1100]\n"
            f"2026-07-28 11:00:00.010 0002 {session_id}|4| INTERNAL STAN}} 6 000456\n"
            f"2026-07-28 11:00:00.020 0002 {session_id}|4| TO HSM : Command=VK\n"
            f"2026-07-28 11:00:00.030 0002 {session_id}|4| HsmResultCode = 99\n"
        )
        file_path = self._create_temp_log(log_content)

        output = parse_and_format_log_file(file_path, mode="compact")
        self.assertIn("Transactions analysées : 1", output)
        self.assertIn("Appels HSM détectés    : 1", output)
        self.assertIn("VK", output)
        self.assertIn("Alertes / Anomalies    : 1", output)

    def test_real_trace_file_token_reduction_if_available(self):
        """Si TRACE_WITH_ERR_ED_05.txt existe, compare la réduction de taille entre mode full et compact."""
        storage_path = Path(__file__).resolve().parent.parent / "storage" / "TRACE_WITH_ERR_ED_05.txt"
        if storage_path.exists():
            full_text = parse_and_format_log_file(str(storage_path), mode="full")
            compact_text = parse_and_format_log_file(str(storage_path), mode="compact")

            self.assertGreater(len(full_text), len(compact_text), "Le mode compact doit être plus court que le mode full.")
            ratio = (1 - (len(compact_text) / len(full_text))) * 100
            print(f"\n[Test Réduction Tokens] Taille Full: {len(full_text)} car, Compact: {len(compact_text)} car -> Réduction de {ratio:.1f}%")

    def test_filter_ghost_transactions_and_heartbeats(self):
        """
        Vérifie que :
        (a) Une vraie transaction avec STAN, RRN et PAN est conservée.
        (b) Un heartbeat (0800 / 0810 / FLD 070 = 301) est rejeté.
        (c) Un fragment sans aucun identifiant (stan, transaction_id, rrn, pan) est rejeté.
        """
        log_content = (
            # (a) Vraie transaction complète (STAN, RRN, PAN)
            "2026-07-28 12:00:00.000 0001 SESS_REAL_001|4| - M.T.I : [1100]\n"
            "2026-07-28 12:00:00.001 0001 SESS_REAL_001|4| INTERNAL STAN} 6 123456\n"
            "2026-07-28 12:00:00.002 0001 SESS_REAL_001|4| PAN} 16 4000123456789010\n"
            "2026-07-28 12:00:00.003 0001 SESS_REAL_001|4| - FLD (037) : (12) : [123456789012]\n"
            "2026-07-28 12:00:00.004 0001 SESS_REAL_001|4| - FLD (039) : (2) : [00]\n"

            # (b) Heartbeat Network Management (MTI 0800)
            "2026-07-28 12:00:01.000 0002 SESS_HB_002|4| - M.T.I : [0800]\n"
            "2026-07-28 12:00:01.001 0002 SESS_HB_002|4| INTERNAL STAN} 6 000001\n"
            "2026-07-28 12:00:01.002 0002 SESS_HB_002|4| - FLD (070) : (3) : [301]\n"

            # (c) Fragment orphelin sans identifiants (aucun STAN, transaction_id, RRN, PAN)
            "2026-07-28 12:00:02.000 0003 SESS_GHOST_003|4| ValidationTlvData End\n"
            "2026-07-28 12:00:02.001 0003 SESS_GHOST_003|4| Transaction incomplete : Identifiants absents\n"
        )
        file_path = self._create_temp_log(log_content)

        transactions = parse_trace_file(file_path)

        # Doit contenir exactement 1 transaction (la vraie transaction a)
        self.assertEqual(len(transactions), 1)
        
        real_tx = transactions[0]
        self.assertEqual(real_tx["identifiers"]["stan"], "123456")
        self.assertEqual(real_tx["identifiers"]["rrn"], "123456789012")
        self.assertEqual(real_tx["identifiers"]["pan"], "4000123456789010")

        # Vérifier que le heartbeat a bien été comptabilisé séparément
        self.assertEqual(transactions.heartbeat_count, 1)

    def test_get_original_auth_data_resultat_minus_one_generates_alert(self):
        """
        GetOriginalAuthData() : résultat -1 doit générer une alerte + failed_functions,
        même si le format n'est pas 'NOK (-1)' littéral.
        """
        log_content = (
            "2026-07-28 12:00:00.000 0001 SESS_GOA_001|4| - M.T.I : [1100]\n"
            "2026-07-28 12:00:00.001 0001 SESS_GOA_001|4| INTERNAL STAN} 6 111222\n"
            "2026-07-28 12:00:00.002 0001 SESS_GOA_001|4| PAN} 16 4000123456789010\n"
            "2026-07-28 12:00:00.003 0001 SESS_GOA_001|4| - FLD (037) : (12) : [601355414052]\n"
            "2026-07-28 12:00:00.010 0001 SESS_GOA_001|4| GetOriginalAuthData() : résultat -1\n"
            "2026-07-28 12:00:00.020 0001 SESS_GOA_001|4| CardInSaf () (NOK)\n"
            "2026-07-28 12:00:00.030 0001 SESS_GOA_001|4| - FLD (039) : (2) : [05]\n"
        )
        file_path = self._create_temp_log(log_content)
        transactions = parse_trace_file(file_path)
        self.assertEqual(len(transactions), 1)
        tx = transactions[0]

        self.assertIn("GetOriginalAuthData", tx["failed_functions"])
        self.assertIn("CardInSaf", tx["failed_functions"])
        self.assertEqual(len(tx["failed_functions"]), 2)

        alerts = tx["alerts_found"]
        self.assertTrue(any("GetOriginalAuthData" in a for a in alerts), alerts)
        self.assertTrue(any("CardInSaf" in a for a in alerts), alerts)
        # Cohérence : autant d'alertes couvrant les fonctions en échec que de failed_functions
        covered = {
            fn for fn in tx["failed_functions"]
            if any(fn in a for a in alerts)
        }
        self.assertEqual(covered, set(tx["failed_functions"]))


class TestFailureRegexFormats(unittest.TestCase):
    def test_resultat_minus_one_formats(self):
        from app.services.log_parser import RE_GENERIC_FAILURE, _build_function_failure_patterns

        patterns = _build_function_failure_patterns()
        p = patterns["GetOriginalAuthData"]
        samples = [
            "GetOriginalAuthData() : résultat -1",
            "GetOriginalAuthData() : resultat -1.",
            "GetOriginalAuthData() result=-1",
            "GetOriginalAuthData (-1)",
            "GetOriginalAuthData() NOK (-1)",
        ]
        for s in samples:
            self.assertTrue(
                p.search(s) or RE_GENERIC_FAILURE.search(s),
                msg=f"Échec non détecté pour: {s!r}",
            )

