# Modèle Elasticsearch et mapping

## 1. Convention de nommage

| Index | Contenu | Template |
|---|---|---|
| `ed-visits-main` | passages valides et avertis du jeu principal | `ed-visits` (pattern `ed-visits-*`) |
| `ed-visits-test` | passages du jeu de tests d'anomalies | `ed-visits` |
| `ed-rejects-main` / `ed-rejects-test` | événements rejetés (audit) | `ed-rejects` (pattern `ed-rejects-*`) |
| `ed-rejects-dlq` | événements refusés par Elasticsearch (DLQ) | `ed-rejects` |

La convention est `<domaine>-<type>-<run>`. Les mappings sont portés par des **index templates**, ce qui garantit
qu'un nouvel index (rejeu, autre lot) reçoit exactement le même modèle.

Fichiers livrés :
- [ed-visits.template.json](../elasticsearch/templates/ed-visits.template.json)
- [ed-rejects.template.json](../elasticsearch/templates/ed-rejects.template.json)

**Application :** `setup/setup.sh` exécute `PUT _index_template/...` puis crée les index.
**Vérification :** `GET ed-visits-main/_mapping` est comparé automatiquement au template par `scripts/validate.py` (section *Mapping conformity*).

## 2. Paramètres de l'index

- `number_of_shards: 1`, `number_of_replicas: 1` : le volume est faible, 1 shard suffit. La réplique se place sur l'autre nœud, donc le cluster est green et résiste à la perte d'un nœud.
- `refresh_interval: 5s` : ingestion par lots, une visibilité quasi temps réel suffit.
- `dynamic: strict` (visites) : tout champ non prévu fait échouer le document. Il est alors capturé par la DLQ, jamais ajouté silencieusement au modèle.
- `date_detection: false` : pas de typage automatique des chaînes.

## 3. Justification des types

| Champ(s) | Type | Justification |
|---|---|---|
| `record_id`, `patient_id`, `stay_id`, `primary_diagnosis_icd10`, `icd10_chapter` | `keyword` | Identifiants et codes : correspondance exacte, filtres, agrégations, cardinalité. Une analyse textuelle les découperait. |
| `gender`, `race_ethnicity`, `arrival_transport`, `disposition`, `age_group`, `arrival_dow`, `arrival_month` | `keyword` | Catégories fermées, normalisées en majuscules par Logstash. Elles servent aux terms aggregations, aux filtres et aux camemberts Kibana. |
| `chief_complaint`, `primary_diagnosis_title` | `text` (analyseur `english`) + sous-champ `.keyword` | **Recherche plein texte** (« pain » trouve « Chest pain », « Abd pain » ; racinisation anglaise) **et** agrégation sur la valeur exacte via `.keyword`. Le normalizer `lowercase_ascii` évite les doublons de casse. |
| `arrival_datetime`, `departure_datetime`, `@timestamp`, `ingest.ingested_at` | `date` | Range queries, `date_histogram`, champ temporel du data view. Logstash convertit déjà en ISO-8601 UTC. |
| `age_years`, `heart_rate_bpm`, `resp_rate_bpm`, `spo2_pct`, `systolic_bp_mmhg`, `diastolic_bp_mmhg`, `medication_reconciliation_count` | `short` | Entiers bornés (< 32 767) : 2 octets au lieu de 8, tri et statistiques possibles. |
| `triage_acuity_esi`, `pain_score_0_10`, `arrival_hour`, `dq.issue_count` | `byte` | Petites échelles entières (1-5, 0-10, 0-23). |
| `temperature_f` | `half_float` | 1 décimale suffit. Précision ~0,06 °F à 100 °F, sur 2 octets. |
| `length_of_stay_hours`, `los_computed_hours`, `shock_index` | `float` | Décimaux utilisés dans des moyennes et percentiles. |
| `admitted_flag`, `is_high_acuity`, `fever_flag` | `boolean` | Filtres binaires, taux calculables par une moyenne. |
| `dq.issues`, `dq.anomaly_categories` | `keyword` (tableaux) | Comptage des anomalies par type dans Kibana et dans la validation. |

**Texte et filtres/agrégations :**
- seuls `chief_complaint` et `primary_diagnosis_title` sont destinés à la recherche textuelle ;
- tous les autres champs servent aux filtres, au tri et aux agrégations (keyword, numériques, dates, booléens).

## 4. Champs absents, invalides ou inattendus

| Situation | Traitement |
|---|---|
| Champ **absent** (cellule vide) | Le CSV est lu avec `skip_empty_columns` : le champ n'existe pas dans le document, sans valeur sentinelle trompeuse. L'anomalie `missing:<champ>` est ajoutée à `dq.issues`. Dans Kibana, le filtre « does not exist » permet de les retrouver. |
| Valeur **invalide** (hors plage, non numérique, catégorie inconnue) | Corrigée ou retirée **avant** Elasticsearch par Logstash : valeur hors plage → champ supprimé ; catégorie inconnue → `UNKNOWN`. La valeur d'origine est conservée dans le texte de l'issue (`out_of_range:heart_rate_bpm=900`). Pas d'`ignore_malformed`, pour qu'aucune erreur de type ne passe inaperçue. |
| Champ **inattendu** | Filtre `prune` (liste blanche) dans Logstash, puis `dynamic: strict` dans ES. Si un champ passait quand même, ES refuserait le document : il irait en DLQ puis dans `ed-rejects-dlq`. |
| Enregistrement **rejeté** | Il n'est jamais mis dans `ed-visits-*`. Il va dans `ed-rejects-*` (mapping `dynamic: false`) : les champs d'audit sont indexés, la ligne brute (`raw_line`) et les valeurs d'origine (`original`, non indexé) sont conservées. |
