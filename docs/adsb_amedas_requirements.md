# ADS-B / AMeDAS 時系列データ収集システム 仕様・構成メモ (v0.2)

作成日時: 2025-12-07 (JST)  
※ v0.1 の要件定義をベースに、ホスト名・サイト名を一般化し、現状実装を反映したメモ。

---

## 0. 前提・全体像

### 0.1 拠点・ホスト構成（一般化）

1. **ADS-B 受信拠点（Raspberry Pi 等）**

   - `adsb_host_1`  
     - 例: サイト `site1`（都市部など）
     - dump1090-fa / skyaware が稼働し `aircraft.json` を提供

   - `adsb_host_2`（任意）  
     - 例: サイト `site2`（沿岸部など）
     - 同様に dump1090-fa / skyaware が稼働

   - 以降、任意のサイト数まで拡張可能（`site3`, `site4`, ...）。

2. **アプリケーション / DB サーバ**

   - 論理名: `app_server`
   - 役割:
     1. PostgreSQL サーバ
     2. AMeDAS 収集スクリプト実行
     3. （将来）Web アプリ / API / ダッシュボードの実行

3. **ネットワーク**

   1. すべてのホストは **Tailscale** でメッシュ接続する。
   2. ADS-B 受信機 (`adsb_host_*`) → DB サーバ (`app_server`) への接続は Tailscale 経由の TCP。
   3. 物理 LAN からの直接接続は、プライベートセグメント（例: `192.168.x.0/24`）のみに制限する。

### 0.2 使用ソフトウェア

1. **ADS-B 関連**

   - dump1090-fa（ADS-B デコーダ、`aircraft.json` 提供）
   - skyaware（`/skyaware/data/aircraft.json` を提供）

2. **DB / 言語・ライブラリ**

   - PostgreSQL 13 以降（パーティションテーブル利用）
   - Python 3.9 以降
     - `requests`
     - `psycopg2-binary`
     - `python-dateutil`（AMeDAS バックフィル用）
     - その他標準ライブラリ

3. **設定管理**

   - `.env` + **dotenvx**
     - `dotenvx run -- python3 ...` で環境変数注入
     - `.env` 本体は Git 管理外
   - `.env.sample` / `config/<host>/env/*.env.sample`
     - 公開用サンプル（ホスト名・サイト名は一般化）

4. **常駐化**

   - `systemd service + timer`
     - `amedas-ingest.service` / `amedas-ingest.timer`（app_server）
     - `adsb-ingest.service` / `adsb-ingest.timer`（各 adsb_host）

---

## 1. システム目的・スコープ

### 1.1 目的

1. 複数拠点（`site1`, `site2`, ...）で受信した **ADS-B データ**を、  
   単一の PostgreSQL に時系列で蓄積する。

2. 各サイトに対応する **気象庁 AMeDAS データ（10分値）** を同じ DB に保存し、  
   将来的に「飛行経路 × 気象」の解析・可視化ができる基盤を整備する。

### 1.2 スコープ（現フェーズ）

1. ADS-B `aircraft.json` からのデータ収集・保存
2. AMeDAS 10分値 JSON からのデータ収集・保存
3. PostgreSQL スキーマとパーティション構成
4. `.env` / dotenvx / systemd による実行環境の標準化
5. 簡易的な SQL によるデータ検証

※ 可視化（Web アプリ / GIS 表示 / Grafana 等）は次フェーズ。

---

## 2. データ要件

### 2.1 ADS-B データ（dump1090-fa / skyaware）

1. **データ源**

   1. 各 ADS-B ホスト上の HTTP エンドポイント（例）:
      - `http://localhost/skyaware/data/aircraft.json`

2. **収集対象フィールド（最低限）**

   1. `snapshot_time`  
      - 収集時刻（UTC, `timestamptz`）
      - 収集スクリプト側で付与

   2. `site_code`  
      - 拠点識別子（例: `site1`, `site2`）

   3. `icao24`  
      - 機体識別子（元 JSON の `hex`、24-bit ICAO address）

   4. その他代表値（存在する場合）

      - `flight`（便名）
      - `squawk`
      - `lat`, `lon`
      - `alt_baro`
      - `gs`（ground speed）
      - `track`

   5. `raw`  
      - 元 JSON 1 レコードを丸ごと `jsonb` として保存

3. **サンプリング間隔**

   1. 標準値: 5 秒ごと
   2. `.env` で `ADSB_POLL_INTERVAL_SEC` を変更可能

4. **一意性**

   - 制約: `UNIQUE (site_code, snapshot_time, icao24)`

5. **時刻**

   - DB にはすべて UTC（`timestamptz`）で保存

### 2.2 気象データ（AMeDAS 10分値）

1. **データ源**

   - 気象庁 AMeDAS JSON（bosai API）
     - 例: `https://www.jma.go.jp/bosai/amedas/data/point/{AMEDAS_ID}/{YYYYMMDD_HH}.json`

2. **対象観測所（例）**

   - `AMEDAS_ID` は `.env` の `AMEDAS_IDS` にカンマ区切りで指定
     - 例: `AMEDAS_IDS=44132,45401,46106`

3. **論理サイトとの対応**

   - `weather_site` テーブルで  
     `site_code`（例: `site1`, `site2`, `site3`）と `amedas_id` を紐付ける

4. **収集粒度**

   1. AMeDAS の 10 分値をそのまま保存
   2. 現在の実装では 3 時間ブロック単位で取得して upsert
      - 例: `2025-12-07T09:00:00+09:00` から 3時間分

5. **時刻**

   1. API の時刻（JST）を UTC に変換して保存（`obs_time timestamptz`）
   2. `PRIMARY KEY (amedas_id, obs_time)` により冪等性を確保

---

## 3. DB スキーマ要件（実装済み）

### 3.1 サイト情報: `weather_site`

**目的**: 論理サイト（`site1` 等）と AMeDAS 観測所 ID を紐付ける。

```sql
CREATE TABLE weather_site (
    code        text PRIMARY KEY,   -- 'site1', 'site2', ...
    amedas_id   text NOT NULL,      -- '44132', '45401', ...
    name        text NOT NULL,      -- 表示名
    lat         double precision,   -- サイト代表地点の緯度
    lon         double precision    -- サイト代表地点の経度
);
```

- 初期データは `sql/schema/010_weather_site.sql` にて投入。

### 3.2 AMeDAS 10分値: `weather_amedas_10m`

```sql
CREATE TABLE weather_amedas_10m (
    amedas_id   text        NOT NULL,
    obs_time    timestamptz NOT NULL,    -- UTC
    temp        real,
    precip_10m  real,
    wind_speed  real,
    wind_dir    integer,
    raw         jsonb       NOT NULL,
    PRIMARY KEY (amedas_id, obs_time)
);
```

- DDL: `sql/schema/020_weather_amedas_10m.sql`
- `INSERT ... ON CONFLICT DO NOTHING` で冪等な upsert を実現。

### 3.3 ADS-B スナップショット: `adsb_aircraft`

#### 3.3.1 親テーブル（パーティション）

```sql
CREATE TABLE adsb_aircraft (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    site_code      text        NOT NULL,
    snapshot_time  timestamptz NOT NULL,
    icao24         text        NOT NULL,
    flight         text,
    squawk         text,
    lat            double precision,
    lon            double precision,
    alt_baro       integer,
    gs             double precision,
    track          double precision,
    raw            jsonb       NOT NULL
) PARTITION BY RANGE (snapshot_time);

ALTER TABLE adsb_aircraft
    ADD CONSTRAINT adsb_aircraft_uniq_site_time_icao24
    UNIQUE (site_code, snapshot_time, icao24);

CREATE INDEX idx_adsb_aircraft_site_time
    ON adsb_aircraft (site_code, snapshot_time);

CREATE INDEX idx_adsb_aircraft_icao24_time
    ON adsb_aircraft (icao24, snapshot_time);
```

- DDL: `sql/schema/030_adsb_aircraft.sql`

#### 3.3.2 月別パーティション（例: 2025-12）

```sql
CREATE TABLE adsb_aircraft_2025_12
    PARTITION OF adsb_aircraft
    FOR VALUES FROM ('2025-12-01 00:00+00')
             TO   ('2026-01-01 00:00+00');
```

- DDL: `sql/schema/031_adsb_partitions_2025_12.sql`
- 将来は日単位パーティションへの拡張も可能。

---

## 4. 収集スクリプト要件（実装概要）

### 4.1 AMeDAS 収集: `src/amedas_ingest.py`

1. **役割**

   1. `.env` から DB / AMeDAS 設定を読み込み
   2. 対象 `AMEDAS_IDS` について、最新版近傍 3時間ブロックを取得
   3. `weather_amedas_10m` に upsert
   4. systemd timer から 10分ごとに実行

2. **主な環境変数（例）**

   ```dotenv
   # DB
   PGHOST=app_server
   PGPORT=5432
   PGDATABASE=adsb_test
   PGUSER=lab_rw
   PGPASSWORD=CHANGE_ME  # 実際のパスワードは .env にのみ記載する

   # AMeDAS
   AMEDAS_IDS=44132,45401,46106
   ```

3. **バックフィル: `src/amedas_backfill.py`**

   1. JST で「どこまで遡るか」を指定し、3時間ブロックでループ取得
   2. API が `404 Not Found` を返す期間はスキップ
   3. 既に実験により **約 10 日以上前**までの取得が可能であることを確認済み

4. **常駐化（app_server 側）**

   - 例: `/etc/systemd/system/amedas-ingest.service`

     ```ini
     [Service]
     Type=oneshot
     WorkingDirectory=/home/appuser/adsb-amedas-lab
     ExecStart=/usr/local/bin/dotenvx run -- python3 src/amedas_ingest.py
     User=appuser
     ```

   - 例: `/etc/systemd/system/amedas-ingest.timer`

     ```ini
     [Timer]
     OnCalendar=*:0/10
     Persistent=true
     Unit=amedas-ingest.service
     ```

### 4.2 ADS-B 収集: `src/adsb_ingest.py`

1. **役割**

   1. `.env` から DB / サイト / JSON URL を読み込み
   2. `AIRCRAFT_JSON_URL` を取得
   3. 有効なレコードをフィルタし、`adsb_aircraft` に upsert
   4. systemd timer から数秒おきに実行

2. **主な環境変数（例）**

   ```dotenv
   # DB
   PGHOST=app_server
   PGPORT=5432
   PGDATABASE=adsb_test
   PGUSER=lab_rw
   PGPASSWORD=CHANGE_ME  # 実際のパスワードは .env にのみ記載する

   # ADS-B
   ADSB_SITE_CODE=site1
   AIRCRAFT_JSON_URL=http://localhost/skyaware/data/aircraft.json
   ADSB_POLL_INTERVAL_SEC=5
   ```

3. **常駐化（各 adsb_host_* 側）**

   - 例: `/etc/systemd/system/adsb-ingest.service`

     ```ini
     [Service]
     Type=oneshot
     WorkingDirectory=/home/pi/adsb-amedas-lab
     ExecStart=/usr/local/bin/dotenvx run -- python3 src/adsb_ingest.py
     User=pi
     ```

   - 例: `/etc/systemd/system/adsb-ingest.timer`

     ```ini
     [Timer]
     OnUnitActiveSec=5
     Unit=adsb-ingest.service
     Persistent=false
     ```

---

## 5. 設定とセキュリティ

### 5.1 環境変数・.env の運用

1. `.env` は **非公開**（Git 管理外）
2. `.env.sample` に公開可能な項目のみ記述し、  
   実際の値（ホスト名 / パスワード / サイトコード実値）は各環境で上書きする。

3. ホスト固有設定例

   - `config/host1/env/adsb.env.sample`
   - `config/host2/env/adsb.env.sample`

### 5.2 DB ユーザ・ロール設計（共通ポリシ）

1. ロール構成（例）

   - `dbuser`  
     - DB オーナー。スキーマ作成やロール作成を行う管理用。
   - `lab_rw`  
     - アプリケーション用 RW ロール（INSERT / SELECT / UPDATE に使用）。
   - `lab_ro`  
     - 解析・ダッシュボード用の R ロール（SELECT のみ）。

2. パスワードは `.env` にのみ記載し、ドキュメントには平文を残さない運用を前提。

### 5.3 ネットワーク制御

1. PostgreSQL の `pg_hba.conf` では、以下のみ許可する方針:

   1. `localhost`（UNIX ソケット / 127.0.0.1）
   2. 物理 LAN（例: `192.168.x.0/24`）
   3. Tailscale アドレス帯（例: `100.64.0.0/10`）

2. インターネットからの直接接続は想定しない。

---

## 6. 時刻・非機能要件

### 6.1 時刻・タイムゾーン

1. DB 上のすべての時刻カラムは `timestamptz`（UTC）。
2. 可視化側で JST や他タイムゾーンに変換して利用する。
3. 全ホストは NTP による時刻同期を前提とする。

### 6.2 容量・パフォーマンス（現時点の想定）

1. サンプリング間隔 5 秒、1〜2 拠点を前提
2. 月次パーティションで 1 年以上のデータ保持を目標
3. 典型クエリ（1 日分など）が数秒程度で返る性能を目安

---

## 7. リポジトリ構成（現状の標準）

```text
adsb-amedas-lab/
  .env.sample              # app_server 用サンプル
  .gitignore
  config/
    host1/
      env/
        adsb.env.sample    # adsb_host_1 用サンプル
      systemd/
        adsb-ingest.service
        adsb-ingest.timer
    app_server/
      systemd/
        amedas-ingest.service
        amedas-ingest.timer
  sql/
    schema/
      010_weather_site.sql
      020_weather_amedas_10m.sql
      030_adsb_aircraft.sql
      031_adsb_partitions_2025_12.sql
  src/
    amedas_ingest.py
    amedas_backfill.py
    adsb_ingest.py
  docs/
    adsb_amedas_requirements_v0_1.md
    adsb_amedas_requirements_v0_2.md   # ← 本ファイル
```

※ `host1` / `app_server` などのディレクトリ名は、公開時に実際のホスト名に依存しないよう汎用名とする。

---

## 8. 将来拡張（メモ）

1. Web アプリ / API
   - サイト・期間・高度レンジなどで絞り込める「飛行機マップ + 天候オーバーレイ」を提供。
2. ダッシュボード
   - Grafana / Superset 等で ADS-B × AMeDAS を俯瞰。
3. データ保持ポリシ
   - 一定期間を過ぎた生データを、パーティション単位でアーカイブ / ダウンロード可能な形に整理。

