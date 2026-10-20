# Plateforme Big Data ED : ELK + Spark (TP3 & TP4)

Plateforme d'analyse et de supervision des passages aux **urgences** (jeu de données synthétique
dérivé de MIMIC-IV-ED demo). Tout tourne avec **Docker Compose** : chaque « machine » du TP est un
conteneur avec un hostname et une IP fixes sur le réseau `bigdata-net` (172.28.0.0/24).

| Machine TP | Conteneur(s) | IP | Rôle | Accès hôte |
|---|---|---|---|---|
| ELK-01 | `es01` + `kibana` | 172.28.0.11 / .13 | Elasticsearch (master+data) + Kibana | http://localhost:9200, http://localhost:5601 |
| ELK-02 | `es02` | 172.28.0.12 | Elasticsearch (master+data) | http://localhost:9201 |
| LOGSTASH-01 | `logstash` | 172.28.0.14 | Ingestion CSV → ES | http://localhost:9600 (API monitoring) |
| SPARK-01 | `spark-master` + `spark-worker` | 172.28.0.21 / .22 | Spark standalone 3.5.5 | http://localhost:8080, :8081, :4040 |

Architecture, choix et justifications : [docs/architecture.md](docs/architecture.md).

## Prérequis (Windows)

1. **WSL 2** : dans un PowerShell *administrateur* : `wsl --install --no-distribution`, puis redémarrer.
2. **Docker Desktop** (backend WSL 2) démarré : `docker info` doit répondre.
3. Mémoire : environ 6 Go pour la stack. Docker Desktop alloue par défaut 50 % de la RAM (8 Go sur une machine
   de 16 Go), ce qui suffit. Pour la fixer, créer `%UserProfile%\.wslconfig` :
   ```ini
   [wsl2]
   memory=8GB
   ```
4. `vm.max_map_count` ≥ 262144 (exigé par Elasticsearch). Docker Desktop le règle déjà, à vérifier :
   `docker run --rm alpine sysctl vm.max_map_count`.
   Sinon : `wsl -d docker-desktop sysctl -w vm.max_map_count=262144`.

## Démarrage

```powershell
docker compose up -d            # es01, es02 -> kibana -> setup -> logstash ; spark-master -> spark-worker
docker compose ps               # tout « healthy », setup « exited (0) »
docker compose logs -f setup    # templates, index, data views
```

Ordre garanti par les healthchecks :
1. `es01` et `es02` démarrent, puis `kibana`.
2. `setup` attend un cluster **green** à 2 nœuds. Il installe ensuite les templates, crée les index, les data views Kibana et règle le fuseau UTC.
3. `logstash` démarre et ingère le CSV.

## Vérifications rapides (TP3)

```powershell
python scripts/check_assignments.py # vérifie les livrables TP3/TP4 sans Docker
python scripts/status.py      # état de chaque service : conteneur + API (cluster, nœuds, index, Kibana, pipelines, Spark)
```

```powershell
curl.exe "localhost:9200/_cat/nodes?v"                  # 2 nœuds, un master (*)
curl.exe "localhost:9200/_cluster/health?pretty"        # status green, number_of_nodes 2
curl.exe "localhost:9200/_cat/indices/ed-*?v"
curl.exe "localhost:9600/_node/stats/pipelines?pretty"  # compteurs Logstash par plugin
```
- Kibana : http://localhost:5601. Stack Management → Index Management / Data Views ; Discover → `ED visits`.
- Première manipulation Elasticsearch : coller [docs/tp3_es_manipulation.txt](docs/tp3_es_manipulation.txt) dans Kibana Dev Tools.

## Ingestion et validation (TP4)

L'ingestion démarre automatiquement avec le service `logstash`. Pour relancer, utiliser `docker compose restart logstash`.
La relance est idempotente : `_id = SHA-256(stay_id)`.

```powershell
python scripts/validate.py                                  # -> docs/validation_results.md
docker compose --profile test run --rm logstash-test        # jeu d'anomalies contrôlées (20 lignes)
python scripts/validate.py --run test                       # -> docs/validation_results_test.md
```
Les rejets se trouvent à deux endroits :
- l'index `ed-rejects-main` (data view « ED rejected events ») ;
- le fichier `logstash/output/rejected-main.ndjson`.

Les refus d'Elasticsearch passent par la DLQ et arrivent dans `ed-rejects-dlq`.

## Spark

```powershell
# TP3 : CSV -> Spark -> résultats (spark/output/tp3/*.csv)
docker compose exec spark-master /opt/spark/bin/spark-submit /opt/spark/jobs/tp3_first_job.py

# Optionnel : ajouter --packages $ES_SPARK_CONNECTOR et TP3_WRITE_ES=true
# pour indexer les trois tableaux de résultats dans Elasticsearch.

# Préparation Jalon 3 : lecture de l'index ES nettoyé (spark/output/analytics/*.csv)
docker compose exec spark-master bash -c '/opt/spark/bin/spark-submit --packages $ES_SPARK_CONNECTOR /opt/spark/jobs/ed_analytics_es.py'
```

## Cloner et reconstruire sur une autre machine

Le dépôt ne contient que les sources. Les images officielles sont téléchargées au premier `up`, et tout le reste
(index, data views, dashboards, sorties) est recréé par la stack.

```powershell
git clone <url-du-depot> big_data
cd big_data
docker compose up -d                       # 1er lancement : téléchargement des images (~7 Go sur disque)
docker compose ps                          # attendre healthy + setup "Exited (0)"
python scripts/validate.py                 # 4908 indexés + 92 rejetés = 5000
```
- `.gitattributes` force les fins de ligne LF : `setup.sh`, les pipelines et le CSV restent valides même si le dépôt
  est cloné sous Windows.
- Les mêmes prérequis s'appliquent (WSL 2, Docker Desktop, `vm.max_map_count`). Les ports 9200, 9201, 5601, 9600, 8080, 8081, 7077 et 4040 doivent être libres.

## Livrables TP4 (dossier `TP2_ELK_Spark_NomBinome/`)

Seuls `README.md` et `5_rapport/rapport_source.html` sont versionnés. Le reste (copies, captures, PDF) se régénère
quand la stack tourne et que l'ingestion est terminée. Prérequis : `pip install playwright` (utilise Microsoft Edge installé).

```powershell
$D = "TP2_ELK_Spark_NomBinome"
python scripts/collect_evidence.py "$D/6_captures"          # sorties brutes des commandes
python scripts/capture_screenshots.py "$D/6_captures"       # captures Kibana + terminal (PNG)
python scripts/render_report_pdf.py "$D/5_rapport/rapport_source.html" "$D/5_rapport/TP2_ELK_Spark_NomBinome.pdf"
```
Les copies des fichiers sources (dossiers 1-4 et 7-9) sont décrites dans `TP2_ELK_Spark_NomBinome/README.md`.

Les résultats TP3 sont écrits **en CSV** (`spark/output/`). Avec `TP3_WRITE_ES=true` et le connecteur,
ils sont aussi écrits dans Elasticsearch. Les résultats analytiques TP4 sont écrits en CSV et dans Elasticsearch,
un index par tableau, remplacé à chaque exécution. Dans Kibana, ils sont visibles via le data view « ED Spark analytics ».

| Index | Contenu |
|---|---|
| `ed-analytics-tp3-disposition`, `-tp3-los-esi`, `-tp3-transport` | job TP3 (CSV brut) |
| `ed-analytics-a1-triage` | A1 : statistiques par niveau ESI |
| `ed-analytics-a2-weekday-hour`, `ed-analytics-a2-monthly` | A2 : affluence jour × heure (1 doc par créneau), tendance mensuelle |
| `ed-analytics-a3-diagnoses` | A3 : diagnostics à risque |

## Arrêt / remise à zéro

```powershell
docker compose down          # garde les données (volumes es01-data, es02-data, ls-data)
docker compose down -v       # supprime aussi les volumes (cluster neuf au prochain up)
```

## Arborescence

```
docker-compose.yml, .env          versions figées + dimensionnement
elasticsearch/config/esXX.yml     configuration de chaque nœud
elasticsearch/templates/          mappings explicites (ed-visits-*, ed-rejects-*)
kibana/kibana.yml
logstash/config/                  logstash.yml (API, DLQ), pipelines.yml
logstash/pipeline/                ed-visits.conf (pipeline principal), ed-dlq.conf
logstash/scripts/ed_quality.rb    règles qualité + tests unitaires
setup/setup.sh                    bootstrap idempotent (templates, index, data views)
spark/jobs/, spark/conf/          jobs PySpark, spark-defaults.conf
scripts/validate.py               bilan chiffré + conformité du mapping
tests/fixtures/                   anomalies contrôlées
docs/                             matière des rapports TP3 / TP4
```
