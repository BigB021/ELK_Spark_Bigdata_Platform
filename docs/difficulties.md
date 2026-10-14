# Difficultés rencontrées

Format : **Problème → Analyse → Solution → Résultat**

### 1. Docker Desktop ne démarre pas
- **Problème :** `docker info` renvoie « Docker Desktop is unable to start ». Le moteur ne répond pas (`_ping` → HTTP 503 dans `com.docker.backend.exe.log`).
- **Analyse :** `wsl --status` indique que *Windows Subsystem for Linux* n'est pas installé. Docker Desktop (backend WSL 2) a besoin de WSL pour sa VM Linux. La virtualisation est bien active (`HypervisorPresent = True`).
- **Solution :** `wsl --install --no-distribution` dans un PowerShell administrateur, redémarrage, relance de Docker Desktop.
- **Résultat :** `docker info` répond et la stack peut être lancée.

### 2. Elasticsearch : `vm.max_map_count` trop faible
- **Problème :** un nœud s'arrête au démarrage avec `max virtual memory areas vm.max_map_count [65530] is too low`.
- **Analyse :** `network.host` n'est pas en loopback, donc ES applique ses *bootstrap checks* de production, qui exigent au moins 262144 zones mémoire mappées.
- **Solution :** `wsl -d docker-desktop sysctl -w vm.max_map_count=262144`. La valeur est déjà correcte par défaut sur les versions récentes de Docker Desktop.
- **Résultat :** les deux nœuds passent les bootstrap checks.

### 3. Mémoire limitée sur le poste
- **Problème :** 6 services Java/Node sur 16 Go de RAM : risque d'OOM-kill (code 137).
- **Analyse :** par défaut, ES prend un heap proportionnel à la RAM visible, Kibana environ 1,5 Go, Logstash 1 Go.
- **Solution :**
  - fixer `mem_limit` et les heaps : ES 512 Mo, Logstash 512 Mo, Kibana `--max-old-space-size=768` ;
  - `SPARK_DAEMON_MEMORY=256m`, executors à 768 Mo ;
  - désactiver le ML d'Elasticsearch.
- **Résultat :** la stack tient dans environ 6 Go.

### 4. Shards non alloués (cluster yellow/red) sur le disque Docker Desktop
- **Problème :** les répliques restent `UNASSIGNED` alors que les 2 nœuds sont présents.
- **Analyse :** le disque virtuel WSL peut paraître rempli au-delà du *high watermark* (90 %), et ES refuse alors d'allouer des shards.
- **Solution :** `cluster.routing.allocation.disk.threshold_enabled: false`. C'est un choix de labo, à ne pas reprendre en production.
- **Résultat :** le cluster est green avec 1 primaire et 1 réplique par index.

### 5. Formats de date hétérogènes et dates impossibles
- **Problème :** 27 dates sont au format `dd/MM/yyyy HH:mm`, et d'autres sont impossibles (`2025-02-30`, mois 13).
- **Analyse :** un seul pattern rejetterait les dates au format européen pourtant correctes. Il faut en revanche rejeter les dates impossibles, que Joda refuse en mode strict.
- **Solution :** filtre `date` avec 2 patterns, une issue `date_format_normalized` pour la variante, un rejet `invalid_date` pour les dates impossibles.
- **Résultat :** les 27 dates sont récupérées et 21 rejets sont justifiés.

### 6. Doublons et code 409 : choix entre `create` et `index`
- **Problème :** avec `action => create`, un doublon provoque une erreur 409 que la DLQ **ne capture pas** (elle ne reçoit que les 400/404). Le doublon disparaîtrait des comptes.
- **Analyse :** il faut détecter les doublons **avant** Elasticsearch pour pouvoir les compter.
- **Solution :**
  - un ensemble partagé des `stay_id` vus pendant le run, dans le script Ruby ;
  - le rejet des doublons vers `ed-rejects-*` ;
  - `action => index` avec `_id = SHA-256(stay_id)` pour l'idempotence entre runs.
- **Résultat :** les doublons sont comptés (2/2 sur le jeu de tests) et un rejeu n'ajoute aucun document.

### 7. Le pipeline `ed-visits` ne démarre pas : tests Ruby
- **Problème :** au démarrage, `Failed to execute action ... pipeline_id:ed-visits` puis `NameError: undefined local variable or method 'base_event' for #<LogStash::Filters::Ruby::Script::TestContext>`. Seul `ed-dlq` tourne.
- **Analyse :** les blocs `test` du script `ed_quality.rb` sont exécutés par le filtre `ruby` dans un objet séparé (`TestContext`). Les méthodes d'aide définies dans le script (`base_event`, `ts`) n'y sont pas visibles.
- **Solution :** les aides deviennent des lambdas globales (`$ed_base_event`, `$ed_ts`), accessibles depuis tous les contextes.
- **Résultat :** les 7 tests unitaires passent au chargement, les 2 pipelines tournent et l'ingestion donne 4 908 indexés + 92 rejetés = 5 000.
