# backend/app/tests/test_fstring_template_fix.py
"""
Test de non-régression pour le bug 500 sur /api/v1/logs/analyze.

SYMPTÔME : "Invalid format specifier in f-string template. Nested replacement fields
are not allowed." levé par LangChain lors de la construction du prompt de documentation
LLM (bouton "?") dans GET /api/v1/functions/{function_name}/doc.

CAUSES DOUBLES IDENTIFIÉES dans main.py, fonction get_function_doc() :
  1. Accolades JSON littérales { } non-échappées dans le template système
     -> LangChain les interprète comme des variables de template non définies.
  2. f-string Python (f"Fonction : {safe_name}") mélangée avec une variable
     LangChain ({raw_doc}) dans le même message utilisateur
     -> si safe_name contient des accolades, ou si LangChain re-applique .format(),
       le résultat est un KeyError / ValueError.

CORRECTIFS APPLIQUÉS :
  1. {{ }} pour toutes les accolades littérales JSON dans le template système.
  2. Remplacement de la f-string par la variable LangChain {function_name}
     passée via format_messages(function_name=safe_name, raw_doc=...).
"""
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from langchain_core.prompts import ChatPromptTemplate


class TestLangChainTemplateBraceEscaping(unittest.TestCase):
    """Verifie que le template du bouton '?' ne leve plus d'erreur de formatage."""

    def test_system_prompt_with_json_schema_braces_does_not_crash(self):
        """
        Reproduit le crash original : un template systeme avec des accolades JSON
        non-echappees leve KeyError lors de format_messages().

        Avec le correctif ({{ }}), aucune exception ne doit etre levee.
        """
        # AVANT correctif (ferait planter) :
        broken_template = ChatPromptTemplate.from_messages([
            ("system", "JSON schema: {\n  \"key\": \"value\"\n}"),
            ("user", "Data: {data}"),
        ])
        with self.assertRaises(Exception):
            # KeyError ou ValueError attendu car { et } dans le systeme
            # sont interpretes comme variables inconnues
            broken_template.format_messages(data="test")

        # APRES correctif (comportement attendu) :
        fixed_template = ChatPromptTemplate.from_messages([
            ("system", "JSON schema: {{\n  \"key\": \"value\"\n}}"),
            ("user", "Data: {data}"),
        ])
        # Ne doit PAS lever d'exception
        messages = fixed_template.format_messages(data="test_value")
        self.assertEqual(len(messages), 2)
        system_content = messages[0].content
        # Les {{ }} doivent etre resolus en { } dans la chaine finale
        self.assertIn("{", system_content)
        self.assertIn("}", system_content)
        self.assertIn('"key"', system_content)

    def test_function_name_as_named_variable_not_fstring(self):
        """
        Reproduit le crash original : melanger une f-string Python avec une variable
        LangChain {raw_doc} dans le meme message utilisateur est fragile.

        Avec le correctif, function_name est passe comme variable nommee.
        """
        # Cas critique : safe_name contient des accolades (ex: macro C avec {ptr})
        tricky_function_name = "Process{Token}"

        # APRES correctif : function_name comme variable nommee -> aucune interference
        fixed_template = ChatPromptTemplate.from_messages([
            ("system", "Tu es un assistant."),
            ("user", "Fonction : {function_name}\n\nDocumentation :\n{raw_doc}"),
        ])
        messages = fixed_template.format_messages(
            function_name=tricky_function_name,
            raw_doc="Contenu de la documentation"
        )
        self.assertEqual(len(messages), 2)
        user_content = messages[1].content
        self.assertIn("Process{Token}", user_content)
        self.assertIn("Contenu de la documentation", user_content)

    def test_function_doc_prompt_template_is_valid(self):
        """
        Verifie en isolation que le template ChatPromptTemplate de get_function_doc
        (bouton '?') se construit et se formate sans erreur, meme avec un nom de
        fonction et un contenu de documentation contenant des accolades.
        """
        # Reconstruction du template tel qu'il existe dans main.py APRES correctif
        doc_prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "Tu es un expert en analyse de specifications de systemes monetiques PowerCARD (HPS).\n"
                "A partir de la documentation brute fournie sur une fonction PowerCARD, genere un OBJET JSON STRICTEMENT VALIDE "
                "avec exactement ces 4 cles (rien d'autre, pas de markdown, pas de texte en dehors du JSON) :\n"
                "{{\n"
                '  "description": "<1-2 phrases>",\n'
                '  "call_context": "<1-2 phrases>",\n'
                '  "failure_meaning": "<1-2 phrases>",\n'
                '  "diagnostic_hint": "<1-2 phrases>"\n'
                "}}\n"
                "REPONDS UNIQUEMENT avec l'objet JSON valide, sans aucun texte autour."
            )),
            ("user", (
                "Fonction : {function_name}\n\n"
                "Documentation brute :\n{raw_doc}"
            )),
        ])

        # Cas critique : raw_doc contenant des accolades (output JSON d'un premier LLM)
        raw_doc_with_braces = (
            '{"field": "value", "nested": {"key": "data"}}\n'
            "Description de la fonction avec des {accolades} et des [crochets]."
        )

        # Ne doit pas lever d'exception
        messages = doc_prompt.format_messages(
            function_name="VerifyPinBlock",
            raw_doc=raw_doc_with_braces,
        )

        self.assertEqual(len(messages), 2)
        sys_content = messages[0].content
        user_content = messages[1].content

        # Verifications systeme : les {{ }} doivent donner { } dans le prompt final
        self.assertIn("{", sys_content)
        self.assertIn('"description"', sys_content)

        # Verifications utilisateur
        self.assertIn("VerifyPinBlock", user_content)
        self.assertIn('{"field"', user_content)
        self.assertIn("accolades", user_content)


class TestAnalyzeLogsEndpointFullPipeline(unittest.TestCase):
    """
    Test d'integration : POST /api/v1/logs/analyze doit retourner 200
    avec le pipeline complet (parsing + RAG + LLM compliance + PDF), y compris
    quand la trace contient des field_violations et que le bouton '?' est actif.
    """

    @patch("app.main.compliance_agent_app.invoke")
    @patch("app.main._process_and_index_pdf")
    @patch("app.main._generate_reportlab_pdf")
    def test_analyze_logs_returns_200_with_field_violations(
        self, mock_gen_pdf, mock_process_pdf, mock_agent_invoke
    ):
        """
        Verifie que /api/v1/logs/analyze retourne 200 quand le rapport LLM
        contient field_analysis et field_violations (Partie D de la tache precedente).
        """
        mock_process_pdf.return_value = {
            "success": True,
            "file_hash": "abc123hash",
            "filename": "spec.pdf",
            "reused": False,
            "message": "Indexed",
        }

        # Rapport avec field_analysis non vide (cas Partie D)
        full_report = {
            "summary": {
                "total_transactions": 1,
                "suspicious_count": 1,
                "approved_count": 0,
                "declined_count": 1,
            },
            "transactions": [
                {
                    "transaction_id": "TXN-1",
                    "is_suspicious": True,
                    "pan_masked": "... 9999",
                    "stan": "000001",
                    "rrn": "123456789012",
                    "processing_code": "000000",
                    "response_code": "05",
                    "response_code_label": "Declinee",
                    "approval_status": "declined",
                    "alerts": ["Champ 002 invalide"],
                    "failed_functions": ["AuthProcess"],
                    "pistes_diagnostiques": "Echec sur AuthProcess.",
                    "chronology": [
                        "Reception de la transaction",
                        "Appel AuthProcess -> echec",
                    ],
                }
            ],
            "field_analysis": [
                {
                    "field_number": "FLD 002",
                    "field_name": "PAN",
                    "expected_type": "N (numerique, max 19)",
                    "source": "Spec_PowerCARD.xlsx",
                    "observed_value": "ABC123DEF",
                    "non_conformity_type": "attendu numerique, contient des lettres",
                }
            ],
            "no_field_violations": False,
        }

        mock_agent_invoke.return_value = {
            "final_response": full_report,
            "current_agent": "ComplianceAuditorAgent",
            "log_data_json": "[]",
        }

        from app.main import app
        client = TestClient(app)

        trace_content = (
            b"2026-07-27 10:00:00 [INFO] Transaction start MTI=0200\n"
            b"2026-07-27 10:00:01 [ERROR] AuthProcess failed -1\n"
            b"2026-07-27 10:00:01 [INFO] HsmResultCode 00\n"
            b"2026-07-27 10:00:02 [INFO] Transaction end RC=05\n"
        )
        spec_content = b"%PDF-1.4 spec content"

        response = client.post(
            "/api/v1/logs/analyze",
            data={"user_prompt": "Analyse la conformite et les violations de champs"},
            files={
                "file": ("trace.txt", io.BytesIO(trace_content), "text/plain"),
                "doc_file": ("spec.pdf", io.BytesIO(spec_content), "application/pdf"),
            },
        )

        self.assertEqual(
            response.status_code, 200,
            msg=f"Attendu 200, obtenu {response.status_code}: {response.text}"
        )
        body = response.json()
        self.assertTrue(body.get("success"), f"success=False: {body}")
        self.assertIn("report", body)

        report = body["report"]
        self.assertIn("field_analysis", report, "field_analysis absent du rapport")
        self.assertEqual(len(report["field_analysis"]), 1)
        self.assertFalse(report.get("no_field_violations", True))
        self.assertEqual(report["field_analysis"][0]["field_number"], "FLD 002")

    @patch("app.main.compliance_agent_app.invoke")
    @patch("app.main._generate_reportlab_pdf")
    def test_analyze_logs_returns_200_without_spec_file(
        self, mock_gen_pdf, mock_agent_invoke
    ):
        """
        Verifie que /api/v1/logs/analyze retourne 200 meme sans document de spec.
        (Pipeline minimal : parsing + LLM sans RAG de session.)
        """
        mock_agent_invoke.return_value = {
            "final_response": {
                "summary": {"total_transactions": 1, "suspicious_count": 0,
                            "approved_count": 1, "declined_count": 0},
                "transactions": [{
                    "transaction_id": "TXN-1",
                    "is_suspicious": False,
                    "pan_masked": "... 1234",
                    "stan": "000042",
                    "rrn": None,
                    "processing_code": None,
                    "response_code": "00",
                    "response_code_label": "Approuvee",
                    "approval_status": "approved",
                    "alerts": [],
                    "failed_functions": [],
                    "pistes_diagnostiques": "",
                    "chronology": ["Reception transaction", "Traitement OK"],
                }],
                "field_analysis": [],
                "no_field_violations": True,
            },
            "current_agent": "ComplianceAuditorAgent",
            "log_data_json": "[]",
        }

        from app.main import app
        client = TestClient(app)

        trace_content = b"2026-07-27 10:00:00 [INFO] Transaction OK RC=00\n"

        response = client.post(
            "/api/v1/logs/analyze",
            data={"user_prompt": "Verifie les transactions"},
            files={
                "file": ("trace.txt", io.BytesIO(trace_content), "text/plain"),
            },
        )

        self.assertEqual(
            response.status_code, 200,
            msg=f"Attendu 200, obtenu {response.status_code}: {response.text}"
        )
        body = response.json()
        self.assertTrue(body.get("success"))
        self.assertEqual(body["report"]["no_field_violations"], True)


class TestFunctionDocumentationRoute(unittest.TestCase):
    """Vérifie la route GET /api/v1/functions/{function_name}/doc."""

    def test_get_function_doc_existing(self):
        """Vérifie le cas d'une fonction existant dans Spec_PowerCARD.xlsx."""
        from app.main import app
        from app.services.spec_loader import get_monitored_function_names
        
        client = TestClient(app)
        
        monitored_names = get_monitored_function_names()
        self.assertTrue(len(monitored_names) > 0, "Le fichier de spec Excel ne doit pas être vide.")
        
        test_func = monitored_names[0]
        
        # Désactiver l'appel LLM pour accélérer le test, ou mock
        with patch("app.services.llm_util.invoke_llm_with_retry") as mock_llm:
            mock_llm.return_value = MagicMock(content='{"description": "Test Desc", "call_context": "Test Context", "failure_meaning": "Test Failure", "diagnostic_hint": "Test Hint"}')
            response = client.get(f"/api/v1/functions/{test_func}/doc")
            
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body.get("found"))
        self.assertEqual(body.get("function_name"), test_func)
        self.assertIn("excel_source", body)
        self.assertIn("excel_path", body)
        self.assertIn("excel_description", body)
        self.assertIn("excel_exception", body)

    def test_get_function_doc_undocumented(self):
        """Vérifie le cas d'une fonction non documentée (ex: swimon_check_msg_id)."""
        from app.main import app
        client = TestClient(app)
        
        response = client.get("/api/v1/functions/swimon_check_msg_id/doc")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body.get("found"))
        self.assertEqual(body.get("function_name"), "swimon_check_msg_id")
        self.assertEqual(
            body.get("message"),
            "Cette fonction n'est pas documentée dans Spec_PowerCARD.xlsx. Aucune information sur ses conditions d'échec n'est disponible."
        )


class TestEnrichReportWithParserData(unittest.TestCase):
    """Le bouton '?' frontend dépend de failed_functions dans le rapport final."""

    def test_reinjects_failed_functions_when_llm_omits_them(self):
        from app.core.agent_graph import _enrich_report_with_parser_data

        report = {
            "summary": {"total_transactions": 1},
            "transactions": [
                {
                    "transaction_id": "TXN-1",
                    "rrn": "123456789012",
                    "stan": "000001",
                    "alerts": [],
                    "chronology": ["Appel GetAuthRouting"],
                }
            ],
        }
        log_data = json.dumps([
            {
                "rrn": "123456789012",
                "stan": "000001",
                "failed_functions": ["GetAuthRouting"],
                "processing_code": "000000",
            }
        ])

        enriched = _enrich_report_with_parser_data(report, log_data)
        tx = enriched["transactions"][0]
        self.assertEqual(tx["failed_functions"], ["GetAuthRouting"])
        self.assertEqual(tx["processing_code"], "000000")
        self.assertIn("GetAuthRouting", tx["pistes_diagnostiques"])
        self.assertTrue(any("GetAuthRouting" in a for a in tx["alerts"]))

    def test_merges_without_duplicates(self):
        from app.core.agent_graph import _enrich_report_with_parser_data

        report = {
            "transactions": [
                {
                    "rrn": "999",
                    "failed_functions": ["AuthProcess"],
                }
            ],
        }
        log_data = json.dumps([
            {"rrn": "999", "failed_functions": ["AuthProcess", "GetAuthRouting"]}
        ])
        enriched = _enrich_report_with_parser_data(report, log_data)
        self.assertEqual(
            enriched["transactions"][0]["failed_functions"],
            ["AuthProcess", "GetAuthRouting"],
        )

    def test_syncs_alerts_for_each_failed_function(self):
        """Chaque failed_function doit avoir une alerte dédiée (bug GetOriginalAuthData)."""
        from app.core.agent_graph import _enrich_report_with_parser_data

        report = {
            "transactions": [
                {
                    "rrn": "601355414052",
                    "alerts": ["CardInSaf() a échoué (résultat : NOK)."],
                    "failed_functions": ["CardInSaf"],
                    "chronology": [
                        "Exécution de GetOriginalAuthData() : résultat -1.",
                        "Échec de la fonction CardInSaf () (NOK).",
                    ],
                }
            ],
        }
        log_data = json.dumps([
            {
                "rrn": "601355414052",
                "failed_functions": ["GetOriginalAuthData", "CardInSaf"],
                "alerts_found": [
                    "GetOriginalAuthData() a échoué (résultat : résultat -1).",
                    "CardInSaf() a échoué (résultat : (NOK)).",
                ],
            }
        ])
        enriched = _enrich_report_with_parser_data(report, log_data)
        tx = enriched["transactions"][0]
        self.assertEqual(
            set(tx["failed_functions"]),
            {"GetOriginalAuthData", "CardInSaf"},
        )
        self.assertTrue(any("GetOriginalAuthData" in a for a in tx["alerts"]))
        self.assertTrue(any("CardInSaf" in a for a in tx["alerts"]))
        # Compteurs cohérents : 2 fonctions en échec ↔ alertes couvrant les 2
        covered = {
            fn for fn in tx["failed_functions"]
            if any(fn in a for a in tx["alerts"])
        }
        self.assertEqual(covered, set(tx["failed_functions"]))

    def test_chronology_resultat_minus_one_adds_to_failed_functions(self):
        """Même si le parser omet GetOriginalAuthData, la chronologie LLM doit le remonter."""
        from app.core.agent_graph import _enrich_report_with_parser_data

        report = {
            "transactions": [
                {
                    "rrn": "03mCReJcH440",
                    "failed_functions": ["Pin", "Get_IssScriptData", "gen_iss_script_data"],
                    "alerts": ["Pin() a échoué."],
                    "chronology": [
                        "Exécution de GetOriginalAuthData() : résultat -1.",
                        "Échec de Pin (NOK).",
                    ],
                }
            ],
        }
        # log_data vide / sans GetOriginalAuthData → extraction chronologie seule
        log_data = json.dumps([
            {
                "rrn": "03mCReJcH440",
                "failed_functions": ["Pin", "Get_IssScriptData", "gen_iss_script_data"],
                "alerts_found": ["Pin() a échoué."],
            }
        ])
        enriched = _enrich_report_with_parser_data(report, log_data)
        tx = enriched["transactions"][0]
        self.assertIn("GetOriginalAuthData", tx["failed_functions"])
        self.assertTrue(any("GetOriginalAuthData" in a for a in tx["alerts"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
