# TP2_ELK_Spark_NomBinome - Livrables du TP4 (Jalon 2)

Plateforme Big Data de supervision des urgences : conception des données et pipeline Logstash.
Rapport complet : `5_rapport/TP2_ELK_Spark_NomBinome.pdf`.

| # | Livrable demandé | Emplacement |
|---|---|---|
| 1 | Jeu de données synthétiques (≥ 5 000 enregistrements) | `1_jeu_de_donnees/ed_synthetic_visits.csv` (5 000 lignes) + `ed_anomaly_samples.csv` (jeu de tests, 20 lignes) |
| 2 | Dictionnaire des données et documentation de génération | `2_dictionnaire_et_generation/data_dictionary.md` |
| 3 | Fichier de mapping Elasticsearch | `3_mapping_elasticsearch/ed-visits.template.json`, `ed-rejects.template.json`, mappings réellement appliqués (`mapping_applique_*.json`), justification |
| 4 | Configuration Logstash complète et réutilisable | `4_configuration_logstash/` : `pipeline/ed-visits.conf`, `pipeline/ed-dlq.conf`, `scripts/ed_quality.rb`, `config/*.yml`, `docker-compose.yml` |
| 5 | Rapport PDF | `5_rapport/TP2_ELK_Spark_NomBinome.pdf` (+ source `rapport_source.html`) |
| 6 | Captures d'écran authentiques | `6_captures/*.png` (18 captures) + sorties brutes `6_captures/preuves_texte/*.txt` |
| 7 | Tableau des volumes générés / lus / indexés / rejetés / dupliqués | `7_bilan_volumes/validation_results.md` (+ `_test.md`) |
| 8 | Anomalies testées et traitements | `8_anomalies/anomaly_strategy.md` |
| 9 | Trois traitements Spark proposés | `9_traitements_spark/spark_analyses.md` + prototype `jobs/` + `resultats/` |

**Bilan :** 5 000 générés · 5 001 lignes lues (en-tête) · **4 908 indexés** (4 596 valid + 312 warning) · **92 rejetés** · 0 doublon · 0 DLQ → 5 000 = 4 908 + 92 + 0.

Reproduction : voir le `README.md` du projet et la section 9 du rapport (`docker compose up -d`, puis `python scripts/validate.py`).
