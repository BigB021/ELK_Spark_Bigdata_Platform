# Spark : premier traitement (TP3) et analyses préparées (TP4 → Jalon 3)

## 1. Environnement

| Élément | Valeur |
|---|---|
| Image | `spark:3.5.5-scala2.12-java17-python3-ubuntu` (image Docker officielle Apache Spark) |
| Java | OpenJDK 17 (`docker compose exec spark-master java -version`) |
| Spark / Scala | 3.5.5 / 2.12 (`spark-submit --version`) |
| Mode | standalone : `spark-master` (master + driver en mode client) et `spark-worker` (2 cores, 1 Go) |
| Connecteur ES | `org.elasticsearch:elasticsearch-spark-30_2.12:8.17.4` (`--packages`) |
| Configuration | [spark-defaults.conf](../spark/conf/spark-defaults.conf) |

## 2. TP3 : Données → Spark → Résultat

Job : [tp3_first_job.py](../spark/jobs/tp3_first_job.py)

```powershell
docker compose exec spark-master /opt/spark/bin/spark-submit /opt/spark/jobs/tp3_first_job.py
```

- **Données :** `datasets/ed_synthetic_visits.csv` (5 000 lignes), lu directement par les executors.
- **Traitement :** cast des types, filtre des lignes plausibles (ESI 1-5, LOS 0-72 h, disposition renseignée), puis 3 agrégations.
- **Résultats CSV :** dans `spark/output/tp3/` :
  - `visits_by_disposition.csv` ;
  - `los_by_triage_acuity.csv` (moyenne et médiane de la LOS par ESI) ;
  - `admission_rate_by_transport.csv`.
- Pour indexer aussi ces trois tableaux, ajouter `--packages $ES_SPARK_CONNECTOR` et
  définir `TP3_WRITE_ES=true`.

## 3. Trois traitements analytiques pour le prochain jalon

La source est l'index nettoyé `ed-visits-main`. Le prototype est dans [ed_analytics_es.py](../spark/jobs/ed_analytics_es.py) :

```powershell
docker compose exec spark-master bash -c '/opt/spark/bin/spark-submit --packages $ES_SPARK_CONNECTOR /opt/spark/jobs/ed_analytics_es.py'
```

| # | Type | Question métier | Champs nécessaires | Résultat attendu |
|---|---|---|---|---|
| A1 | Calcul statistique / agrégation | La durée de séjour et le taux d'hospitalisation suivent-ils la gravité au triage ? | `triage_acuity_esi`, `length_of_stay_hours`, `admitted_flag`, `shock_index` | Table par ESI : nb de passages, LOS moyenne / médiane / P90, % hospitalisés, shock index moyen. On attend une LOS et une hospitalisation décroissantes de ESI 1 à 5. |
| A2 | Analyse temporelle | Quand l'affluence est-elle maximale ? L'activité évolue-t-elle ? | `arrival_hour`, `arrival_dow`, `arrival_month`, `length_of_stay_hours`, `admitted_flag` | Matrice 7 jours × 24 h des arrivées (pics de fin de matinée, creux de nuit), tendance mensuelle des volumes, LOS et % d'hospitalisation, pour dimensionner les équipes. |
| A3 | Analyse métier | Quels diagnostics consomment le plus de lits (hospitalisation, séjour > 6 h) ? | `primary_diagnosis_icd10`, `primary_diagnosis_title`, `admitted_flag`, `length_of_stay_hours`, `triage_acuity_esi` | Classement des diagnostics (≥ 50 passages) par taux d'hospitalisation et de séjours longs. Exemple : infarctus, sepsis et AVC en tête ; céphalées et lombalgies en bas. |

Résultats écrits dans `spark/output/analytics/*.csv`.

## 4. Limites du jeu de données et améliorations prévues

- **Données synthétiques :** les corrélations (gravité, diagnostic, hospitalisation) sont simplifiées. Il n'y a pas de saisonnalité épidémique réaliste.
- **Volume :** 5 000 passages, soit environ 18 mois d'un petit service. Pour tester la montée en charge au prochain TP, on peut multiplier le volume par un générateur paramétré (graine fixe), à 100 000 lignes ou plus.
- **Un seul diagnostic par passage,** pas de table de mouvements. On pourrait ajouter les diagnostics secondaires et les horaires de triage et de prise en charge (délai d'attente).
- **Fuseau horaire :** les dates sont traitées en UTC, faute d'information de fuseau dans la source.
- **Doublons absents** du jeu principal. Le mécanisme n'est démontré que par le jeu de tests ; on pourrait injecter des doublons dans le prochain lot.
- **Parallélisme :** passer à plusieurs workers Spark et à un index à plusieurs shards pour que la lecture ES soit vraiment parallèle (1 partition Spark par shard).
