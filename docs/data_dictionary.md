# Dictionnaire des données et génération

## 1. Scénario métier

Le service des urgences (*Emergency Department, ED*) d'un hôpital enregistre chaque passage : arrivée, triage,
constantes vitales, diagnostic et orientation de sortie. La direction veut :
- suivre l'activité (volumes par heure, jour, mois) et la gravité (ESI) ;
- mesurer les **durées de séjour** (LOS) et repérer les séjours prolongés (*boarding*) ;
- connaître les **taux d'hospitalisation** par diagnostic et par mode d'arrivée ;
- contrôler la **qualité des données** saisies.

## 2. Origine et génération du jeu de données

- **Fichier :** `datasets/ed_synthetic_visits.csv`. Il est au format CSV (UTF-8, séparateur `,`, guillemets `"`, fins de ligne LF) et contient 1 ligne d'en-tête et **5 000 enregistrements**.
- **Base :** le schéma et les distributions s'inspirent du jeu public **MIMIC-IV-ED demo** (tables `edstays`, `triage`, `diagnosis`, `medrecon`).
- **Données synthétiques :** aucune donnée réelle. Les patients sont des identifiants `SYN-P…`, les séjours `SYN-S…`, et les dates sont projetées sur 2025-01 → 2026-06.
- **Méthode de génération** (version augmentée fournie) :
  1. tirage des valeurs selon les fréquences observées dans la démo : diagnostics ICD-10 associés aux motifs de consultation, constantes cohérentes avec la gravité, hospitalisations plus fréquentes pour les ESI 1-2 ;
  2. injection contrôlée de 5 % d'anomalies (catalogue : [anomaly_strategy.md](anomaly_strategy.md)).
- **Reproductibilité :** le fichier livré est la référence figée. Le profilage est reproductible : `scripts/validate.py` recompte le nombre de lignes, et les chiffres du catalogue d'anomalies sont recalculables à partir du CSV.

Le jeu respecte les contraintes du TP4 :

| Contrainte TP4 | Valeur |
|---|---|
| ≥ 5 000 enregistrements | 5 000 |
| ≥ 12 champs | 24 champs sources + 9 champs dérivés |
| ≥ 5 catégories métier | 9 dispositions, 6 modes d'arrivée, 8 origines, 5 niveaux ESI, 26 diagnostics |
| ≥ 95 % conformes | 4 908 enregistrements indexables (98,2 %) |
| ≥ 5 % d'anomalies | voir le bilan dans [validation_results.md](validation_results.md) |
| Diversité des types | identifiants, textes, entiers, décimaux, catégories, dates, booléens |

## 3. Dictionnaire des champs sources

| # | Champ | Type logique | Exemple | Domaine valide | Type ES |
|---|---|---|---|---|---|
| 1 | `record_id` | identifiant | ED000001 | unique, obligatoire | keyword |
| 2 | `patient_id` | identifiant | SYN-P000027 | un patient a plusieurs passages | keyword |
| 3 | `stay_id` | identifiant (clé métier) | SYN-S0100001 | unique, obligatoire | keyword |
| 4 | `arrival_datetime` | date | 2025-01-20 10:14:00 | `yyyy-MM-dd HH:mm:ss`, passé, obligatoire | date |
| 5 | `departure_datetime` | date | 2025-01-20 13:05:00 | ≥ arrivée | date |
| 6 | `length_of_stay_hours` | décimal | 2.85 | = départ − arrivée, en heures | float |
| 7 | `gender` | catégorie | F | F, M, OTHER, UNKNOWN | keyword |
| 8 | `age_years` | entier | 24 | 0-120 | short |
| 9 | `race_ethnicity` | catégorie | WHITE | 8 modalités (WHITE, BLACK/AFRICAN AMERICAN, HISPANIC/LATINO, ASIAN, MULTIPLE RACE/ETHNICITY, OTHER, UNKNOWN, PATIENT DECLINED TO ANSWER) | keyword |
| 10 | `arrival_transport` | catégorie | AMBULANCE | WALK IN, AMBULANCE, HELICOPTER, POLICE, OTHER, UNKNOWN | keyword |
| 11 | `triage_acuity_esi` | catégorie ordinale | 2 | 1 (vital) à 5 (non urgent) | byte |
| 12 | `chief_complaint` | texte libre | Wheezing, cough | motif de consultation | text + keyword |
| 13 | `temperature_f` | décimal | 97.7 | 90-110 °F | half_float |
| 14 | `heart_rate_bpm` | entier | 80 | 20-250 | short |
| 15 | `resp_rate_bpm` | entier | 13 | 4-60 | short |
| 16 | `spo2_pct` | entier | 95 | 50-100 | short |
| 17 | `systolic_bp_mmhg` | entier | 128 | 50-260 | short |
| 18 | `diastolic_bp_mmhg` | entier | 68 | 20-160 | short |
| 19 | `pain_score_0_10` | entier | 6 | 0-10 | byte |
| 20 | `primary_diagnosis_icd10` | code | R51.9 | format ICD-10-CM `A00(.0000)` | keyword |
| 21 | `primary_diagnosis_title` | texte | Headache, unspecified | libellé ICD-10 | text + keyword |
| 22 | `medication_reconciliation_count` | entier | 6 | 0-60 | short |
| 23 | `disposition` | catégorie | HOME | HOME, ADMITTED, TRANSFER, LEFT WITHOUT BEING SEEN, LEFT AGAINST MEDICAL ADVICE, ELOPED, EXPIRED, OTHER | keyword |
| 24 | `admitted_flag` | booléen | false | doit valoir `disposition == ADMITTED` | boolean |

## 4. Champs dérivés (calculés par Logstash)

| Champ | Type ES | Règle | Usage |
|---|---|---|---|
| `@timestamp` | date | = `arrival_datetime` (UTC) | axe temporel de Kibana |
| `los_computed_hours` | float | (départ − arrivée) / 3600 | contrôle de cohérence de la LOS |
| `age_group` | keyword | 0-17, 18-34, 35-49, 50-64, 65-79, 80+ | agrégations |
| `arrival_hour` | byte | heure d'arrivée 0-23 | analyse temporelle |
| `arrival_dow` | keyword | `1-MON` … `7-SUN` (triable) | analyse temporelle |
| `arrival_month` | keyword | `yyyy-MM` | tendance mensuelle |
| `is_high_acuity` | boolean | ESI ≤ 2 | filtre « patients graves » |
| `fever_flag` | boolean | température ≥ 100.4 °F | filtre clinique |
| `shock_index` | float | FC / PAS (> 1 = signe d'alerte) | indicateur de gravité |
| `icd10_chapter` | keyword | 1ʳᵉ lettre du code ICD-10 | regroupement des diagnostics |
| `dq.status` | keyword | valid / warning | qualité |
| `dq.issues` | keyword[] | liste des anomalies détectées | qualité |
| `dq.anomaly_categories` | keyword[] | catégories d'anomalies | qualité |
| `dq.issue_count` | byte | nombre d'anomalies | qualité |
| `ingest.*` | keyword/date | run_id, pipeline, source_file, ingested_at | traçabilité |
