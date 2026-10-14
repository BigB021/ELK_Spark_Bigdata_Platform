# Pipeline Logstash

## 1. Installation et configuration

- **Image :** `docker.elastic.co/logstash/logstash:8.17.4`, même version qu'Elasticsearch et Kibana.
- **Mémoire :** heap 256-512 Mo, limite du conteneur à 1 Go.
- **Fichiers montés :**

| Fichier | Rôle |
|---|---|
| [logstash.yml](../logstash/config/logstash.yml) | API de monitoring sur :9600, `pipeline.ecs_compatibility: disabled` (noms de champs métier conservés), **DLQ activée** |
| [pipelines.yml](../logstash/config/pipelines.yml) | 2 pipelines : `ed-visits` (2 workers, lots de 250) et `ed-dlq` |
| [ed-visits.conf](../logstash/pipeline/ed-visits.conf) | pipeline principal (Input / Filter / Output), commenté |
| [ed-dlq.conf](../logstash/pipeline/ed-dlq.conf) | retraitement de la dead letter queue |
| [ed_quality.rb](../logstash/scripts/ed_quality.rb) | règles de qualité + tests unitaires |

Le pipeline est **paramétré** par variables d'environnement. Il est donc réutilisable pour un autre fichier ou un autre lot sans modification :

| Variable | Rôle | Valeur `logstash` | Valeur `logstash-test` |
|---|---|---|---|
| `INPUT_FILE` | fichier lu | `/data/ed_synthetic_visits.csv` | `/fixtures/ed_anomaly_samples.csv` |
| `RUN_ID` | suffixe des index | `main` | `test` |
| `EXIT_AFTER_READ` | arrêt en fin de fichier | `false` (service) | `true` (batch) |

## 2. Étapes

```
file (read) ─► mutate provenance ─► csv ─► snapshot ─► mutate (casse, espaces)
           ─► translate x4 (listes blanches) ─► date x2 ─► ruby (règles qualité)
           ─► fingerprint (_id) ─► prune (liste blanche) ─┬─► ES ed-visits-<run>
                                                         └─► ES ed-rejects-<run> + fichier ndjson
ES refus 400/404 ─► DLQ ─► pipeline ed-dlq ─► ES ed-rejects-dlq
```

| # | Plugin (`id`) | Rôle |
|---|---|---|
| Input | `file` (`in_csv_file`) | Mode `read` (fichier complet). `sincedb_path=/dev/null` : relecture à chaque démarrage, sans risque car l'indexation est idempotente. Le fichier source n'est jamais supprimé (`file_completed_action=log`). |
| 0 | `mutate` (`f_provenance`) | Copie de la ligne brute, chemin source, `ingest.run_id`, `ingest.pipeline`. |
| 1 | `csv` (`f_csv_parse`) | 24 colonnes **explicites**, en-tête ignoré (`skip_header`), cellules vides → champ absent. |
| 2 | `ruby` (`f_snapshot_original`) | Copie des valeurs d'origine, conservée avec les rejets. |
| 3 | `mutate` (`f_normalize_case`) | Majuscules pour les catégories et codes, minuscules pour le booléen, suppression des espaces. |
| 4 | `translate` (`f_dict_*`) | Référentiels des valeurs autorisées et synonymes (`MALE`→`M`, `WALK-IN`→`WALK IN`). Valeur inconnue → marqueur `__INVALID__`. |
| 5 | `date` (`f_date_arrival`, `f_date_departure`) | Format canonique `yyyy-MM-dd HH:mm:ss` + variante `dd/MM/yyyy HH:mm`, en UTC. Une date impossible (30 février) fait échouer le parsing, avec le tag `_arrival_date_invalid`. |
| 6 | `ruby` (`f_quality_rules`) | Conversion de types, plages plausibles, dates futures, cohérence départ/arrivée et LOS, flag hospitalisation, doublons, champs dérivés, statut et routage. Voir [anomaly_strategy.md](anomaly_strategy.md). |
| 7 | `fingerprint` (`f_fp_stay_id` / `f_fp_reject`) | `_id` déterministe (SHA-256), ce qui rend les rejeux idempotents. |
| 8 | `prune` (`f_prune_unexpected`) | Liste blanche des champs du mapping : aucun champ technique (`host`, `message`, `tags`, `@version`) n'est envoyé dans l'index strict. |
| Output | `elasticsearch` (`out_es_valid`) | `ed-visits-<run>`, `document_id` = empreinte, `hosts` = es01 **et** es02 (répartition et bascule). |
| Output | `elasticsearch` (`out_es_rejected`) + `file` (`out_file_rejected`) | `ed-rejects-<run>` + `logstash/output/rejected-<run>.ndjson` (preuve hors ES). |

## 3. Exécution et observation

```powershell
docker compose up -d logstash                       # ingestion du jeu principal
docker compose logs -f logstash                     # démarrage, tests ruby, fin de lecture
curl.exe "localhost:9600/_node/stats/pipelines/ed-visits?pretty"   # events in / filtered / out par plugin
docker compose restart logstash                     # rejeu complet (idempotent)
docker compose --profile test run --rm logstash-test   # jeu d'anomalies
python scripts/validate.py                          # bilan chiffré -> docs/validation_results.md
```

Chaque plugin ayant un `id`, la réponse de `_node/stats/pipelines` donne directement les volumes :
- lignes lues : `in_csv_file.events.out` ;
- documents envoyés : `out_es_valid.events.in` et `out_es_rejected.events.in`.

Écart attendu entre lignes lues et enregistrements : **+1** (l'en-tête est lu puis supprimé par le filtre `csv`).

## 4. Visualisations Kibana suggérées (captures du rapport)

Data view **ED visits** (`ed-visits-*`, champ temporel `@timestamp`) :

| Visualisation (Lens) | Configuration |
|---|---|
| Passages dans le temps | Bar vertical, `@timestamp` (intervalle semaine), décomposé par `triage_acuity_esi` |
| Orientation de sortie | Donut, top values `disposition` |
| LOS moyenne par ESI | Bar, axe X `triage_acuity_esi`, axe Y moyenne de `length_of_stay_hours` |
| Heatmap d'affluence | Heatmap, X = `arrival_hour`, Y = `arrival_dow`, count |
| Top diagnostics | Table, top 10 `primary_diagnosis_title.keyword`, count + taux `admitted_flag` |
| Qualité des données | Bar horizontal, top values `dq.anomaly_categories`, décomposé par `dq.status` |

Data view **ED rejected events** : table des `reject_reasons` et Discover sur `raw_line`.
Recherche plein texte dans Discover : `chief_complaint : "pain"`.
