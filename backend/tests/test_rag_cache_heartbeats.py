# tests/test_rag_cache_heartbeats.py
import unittest
import os
import tempfile
from pathlib import Path

from app.services.log_parser import parse_trace_file, parse_and_format_log_file
from app.rag.retriever import (
    find_chunks_by_file_hash,
    update_session_id_for_file_hash,
    count_session_chunks,
    query_command_code,
    purge_chunks_by_session_id,
    purge_chunks_by_file_hash
)


# --- TRACE FICTIVE COMPRENANT UN MÉLANGE DE HEARTBEATS ET DE VRAIES TRANSACTIONS ---
SAMPLE_TRACE = """
2026-08-03 10:00:00.000 INFO SESSION_HB1| - M.T.I : [0800] Network Management Request
2026-08-03 10:00:00.100 INFO SESSION_HB1| FLD (070) : (03) : [301]
2026-08-03 10:00:00.200 INFO SESSION_HB1| End

2026-08-03 10:01:00.000 INFO SESSION_TX1| - M.T.I : [0100] Authorization Request
2026-08-03 10:01:00.100 INFO SESSION_TX1| TRANSACTION_IDENTIFIER} 10 TXN_1001
2026-08-03 10:01:00.200 INFO SESSION_TX1| INTERNAL STAN} 6 000101
2026-08-03 10:01:00.300 INFO SESSION_TX1| PAN} 16 4111111111111111
2026-08-03 10:01:00.400 INFO SESSION_TX1| FLD (037) : (12) : [123456789012]
2026-08-03 10:01:00.500 INFO SESSION_TX1| FLD (039) : (02) : [00]
2026-08-03 10:01:00.600 INFO SESSION_TX1| End

2026-08-03 10:02:00.000 INFO SESSION_HB2| - M.T.I : [0810] Network Management Response
2026-08-03 10:02:00.100 INFO SESSION_HB2| FLD (070) : (03) : [301]
2026-08-03 10:02:00.200 INFO SESSION_HB2| End

2026-08-03 10:03:00.000 INFO SESSION_TX2| - M.T.I : [0200] Financial Transaction Request
2026-08-03 10:03:00.100 INFO SESSION_TX2| TRANSACTION_IDENTIFIER} 10 TXN_2002
2026-08-03 10:03:00.200 INFO SESSION_TX2| INTERNAL STAN} 6 000202
2026-08-03 10:03:00.300 INFO SESSION_TX2| PAN} 16 5222222222222222
2026-08-03 10:03:00.400 INFO SESSION_TX2| FLD (037) : (12) : [987654321098]
2026-08-03 10:03:00.500 INFO SESSION_TX2| FLD (039) : (02) : [51]
2026-08-03 10:03:00.600 INFO SESSION_TX2| End
"""


class TestRAGCacheHeartbeats(unittest.TestCase):

    def test_heartbeat_exclusion(self):
        """TÂCHE 3 : Vérifie l'exclusion stricte des 0800/0810/301 dans le log_parser."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write(SAMPLE_TRACE)
            temp_path = f.name

        try:
            # Parsing sans heartbeats
            parsed_txs = parse_trace_file(temp_path, include_heartbeats=False)
            self.assertEqual(len(parsed_txs), 2, f"Attendu 2 transactions métiers, obtenu {len(parsed_txs)}")
            self.assertEqual(parsed_txs.heartbeat_count, 2, f"Attendu 2 heartbeats comptabilisés, obtenu {parsed_txs.heartbeat_count}")

            for tx in parsed_txs:
                self.assertNotIn(tx.get("mti"), {"0800", "0810"}, f"MTI Heartbeat fuite dans le parsing: {tx.get('mti')}")
                self.assertFalse(tx.get("is_heartbeat"), "is_heartbeat=True détecté dans la liste finale")

            # Formatage texte pour validation_agent_graph
            formatted_text = parse_and_format_log_file(temp_path, mode="compact")
            self.assertIn("Messages heartbeat (0800/0810) : 2 détectés et ignorés", formatted_text)
            self.assertNotIn("MTI 0800", formatted_text)
            self.assertNotIn("MTI 0810", formatted_text)
            self.assertIn("0100", formatted_text)
            self.assertIn("0200", formatted_text)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_command_code_regex_extraction(self):
        """TÂCHE 1 : Vérifie l'extraction regex des codes commande et réponse (ex: EC (ED))."""
        import re
        cmd_pair_regex = re.compile(r"\b([A-Z0-9]{2})\s*(?:\/|\s+and\s+|\s*\(\s*)\s*([A-Z0-9]{2})\s*\)?", re.IGNORECASE)
        
        sample_text = "Table 4-12: Host Command EC (ED) Response Error Codes. Codes 00, 01, 10, 11, 17, 27, 68, 69."
        m = cmd_pair_regex.search(sample_text)
        self.assertIsNotNone(m, "Le regex de paire de commandes n'a pas matché 'EC (ED)'")
        self.assertEqual(m.group(1).upper(), "EC")
        self.assertEqual(m.group(2).upper(), "ED")


if __name__ == "__main__":
    unittest.main()
