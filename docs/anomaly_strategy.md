# Anomalies : catalogue et stratégie de traitement

## 1. Principe

Chaque événement reçoit un **statut qualité** calculé par [ed_quality.rb](../logstash/scripts/ed_quality.rb) :

| Statut | Signification | Destination |
|---|---|---|
| `valid` | aucune anomalie | `ed-visits-<run>` |
| `warning` | anomalie non bloquante : le champ fautif est retiré ou corrigé, l'anomalie est tracée dans `dq.issues` | `ed-visits-<run>` |
| `rejected` | l'enregistrement n'est pas exploitable (pas d'identité de séjour ou pas d'ancrage temporel fiable) | `ed-rejects-<run>` + `logstash/output/rejected-<run>.ndjson` |
| *(DLQ)* | refus par Elasticsearch (erreur de mapping, 400/404) | dead letter queue → pipeline `ed-dlq` → `ed-rejects-dlq` |

**Règle de décision.** On rejette quand l'enregistrement fausserait les analyses temporelles ou d'unicité :
- sans `stay_id` → impossible de dédoublonner ;
- sans date d'arrivée valide → impossible de placer le passage dans le temps ;
- départ avant arrivée → LOS négative.

Pour les autres anomalies, on garde l'enregistrement et on retire seulement la valeur fausse. Les autres
champs restent utiles : un âge erroné n'invalide pas un diagnostic.

**Aucune perte silencieuse :**
- chaque événement lu sort par exactement une des trois voies (indexé, rejeté, DLQ) ;
- `scripts/validate.py` vérifie que *générés = indexés + rejetés + DLQ*.

## 2. Catalogue des anomalies du jeu principal (profilage du CSV)

| Catégorie (`dq.anomaly_categories`) | Anomalie | Occurrences dans le CSV | Traitement | Statut |
|---|---|---:|---|---|
| `missing_field` | `stay_id` vide | 8 | rejet `missing:stay_id` | rejected |
| `missing_field` | `arrival_datetime` vide | 11 | rejet `missing:arrival_datetime` | rejected |
| `missing_field` | `departure_datetime` vide (patient encore présent ?) | 7 | champ absent, LOS déclarée conservée si plausible | warning |
| `missing_field` | `patient_id`, `gender`, `age_years`, `arrival_transport`, ESI, `chief_complaint`, `heart_rate_bpm`, `spo2_pct`, ICD-10, `disposition`, `admitted_flag` vides | 5 à 13 par champ | champ absent + issue `missing:<champ>` | warning |
| `invalid_date` | date impossible : `2025-02-30`, `2025-13-01`, `2026-04-31` | 21 | échec du filtre `date` (Joda strict) → rejet | rejected |
| `invalid_date` | date future (2031) | 25 | rejet `future_date` (date > instant d'ingestion) | rejected |
| `format_variant` | date au format `dd/MM/yyyy HH:mm` | 27 | **normalisée** (2ᵉ pattern du filtre `date`) + issue `date_format_normalized` | warning |
| `inconsistency` | départ antérieur à l'arrivée | 27 | rejet `departure_before_arrival` | rejected |
| `inconsistency` | `admitted_flag` ≠ (`disposition == ADMITTED`) | 24 (17 corrigés dans l'index ; les autres sont rejetés ou ont une disposition inconnue) | flag **recalculé** depuis la disposition | warning |
| `inconsistency` | LOS déclarée ≠ LOS calculée (> 0,1 h d'écart) | 38 (dont 13 sur des lignes indexées, les autres rejetées) | LOS remplacée par la valeur calculée | warning |
| `invalid_numeric` | âge −4 / 245 | 7 | champ retiré | warning |
| `invalid_numeric` | température −98.6 / 0 / 9.86 / 986 °F | 18 | champ retiré | warning |
| `invalid_numeric` | FC −72 / 0 / 900 | 18 | champ retiré | warning |
| `invalid_numeric` | SpO2 150 / −5 / 0 | 11 | champ retiré | warning |
| `invalid_numeric` | PAS 940 / 12 | 11 | champ retiré | warning |
| `invalid_numeric` | douleur −3 / 11 | 20 | champ retiré | warning |
| `outlier` | LOS > 72 h (jusqu'à 120 h) | 12 | conservée (séjour prolongé possible) mais signalée `los_over_72h` | warning |
| `unknown_category` | gender `Q`, `X-NOT-SPECIFIED` | 8 | → `UNKNOWN` | warning |
| `unknown_category` | transport `TELEPORT`, `DRONE` | 14 | → `UNKNOWN` | warning |
| `unknown_category` | race `MARTIAN` | 14 | → `UNKNOWN` | warning |
| `unknown_category` | disposition `PENDING_REVIEW`, `SENT_TO_MARS` | 10 | → `UNKNOWN` (le flag n'est alors pas recalculé) | warning |
| `unknown_category` | ESI `0`, `9` | 14 | champ retiré (échelle 1-5) | warning |
| `duplicate` | même `stay_id` déjà vu dans le run | 0 dans le CSV (testé avec le jeu de tests) | 1ʳᵉ occurrence indexée, suivantes rejetées `duplicate:stay_id=…` | rejected |
| `parse_error` | ligne CSV mal formée | 0 | rejet `csv_parse_failure` | rejected |

Un même enregistrement peut cumuler plusieurs anomalies. Pour le jeu principal, le profilage prévoit
**92 rejets** (25 futures + 27 départ<arrivée + 21 dates impossibles + 11 arrivées manquantes + 8 `stay_id` manquants)
et **4 908 documents indexés**. Les chiffres mesurés se trouvent dans [validation_results.md](validation_results.md).

## 3. Doublons : double protection

1. **Dans un run** : un ensemble partagé des `stay_id` déjà vus (thread-safe, commun aux workers). Le 2ᵉ passage
   portant le même `stay_id` est rejeté avec la raison `duplicate`, il est donc compté.
2. **Entre runs** : `_id = SHA-256(stay_id)`. Relancer l'ingestion **met à jour** les mêmes documents au lieu de
   les dupliquer (indexation idempotente). Dans `ed-rejects-*`, `_id = SHA-256(ligne brute + n° d'occurrence)`.

## 4. Anomalies générées et erreurs d'ingestion

| Type | Origine | Où les voir |
|---|---|---|
| Anomalies **générées** (volontaires) | dans le CSV | `dq.issues` / `dq.anomaly_categories` (indexés), `reject_reasons` (rejetés) |
| Erreurs **d'ingestion** (techniques) | refus ES, mapping, réseau | `ed-rejects-dlq` (`dlq.reason`), logs `docker compose logs logstash`, compteurs `:9600/_node/stats/pipelines` |

## 5. Tests des catégories d'anomalies

Le jeu [tests/fixtures/ed_anomaly_samples.csv](../tests/fixtures/ed_anomaly_samples.csv) contient 20 lignes, une par cas :

| Ligne | Cas testé | Attendu |
|---|---|---|
| T001, T002 | enregistrements conformes | valid |
| T003 | `patient_id` manquant | warning `missing:patient_id` |
| T004 | `stay_id` manquant | rejected |
| T005 | arrivée manquante | rejected |
| T006, T007 | dates impossibles (30 février, mois 13) | rejected `invalid_date` |
| T008 | date future 2031 | rejected `future_date` |
| T009 | départ < arrivée | rejected `departure_before_arrival` |
| T010 | date `dd/MM/yyyy` | warning `date_format_normalized` |
| T011 | départ manquant | warning `missing:departure_datetime` |
| T012 | âge, température, FC, SpO2, PAS, douleur hors plage | warning, 6 champs retirés |
| T013 | gender/race/transport/ESI/disposition inconnus | warning, valeurs → `UNKNOWN` |
| T014 | `admitted_flag=true` avec disposition HOME | warning, flag corrigé à `false` |
| T015 | LOS déclarée 9,75 h vs 2 h calculées + flag incohérent | warning `los_mismatch`, `admitted_flag_mismatch` |
| T016 | LOS 120 h | warning `los_over_72h` |
| T017 | code ICD-10 invalide | warning `invalid_code` |
| T018 | `stay_id` déjà vu (TS-001) | rejected `duplicate` |
| ligne 20 | copie exacte de T001 | rejected `duplicate` |
| T020 | température non numérique (`abc`) | warning `not_numeric` |

Résultat attendu : **12 indexés** (2 valid + 10 warning) et **8 rejetés**, dont 2 doublons.
Le résultat mesuré est dans `docs/validation_results_test.md`.

Le script Ruby contient aussi des **tests unitaires** (blocs `test`), exécutés par Logstash au démarrage du
pipeline. Si l'un d'eux échoue, le pipeline ne démarre pas.
