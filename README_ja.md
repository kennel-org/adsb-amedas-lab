# ADS-B + AMeDAS Lab

このリポジトリは、複数拠点で受信した ADS-B データと、気象庁 AMeDAS の 10 分値を PostgreSQL に蓄積するためのラボ環境用コードとスキーマをまとめたものです。

開発用 Web ビューアで表示した ADS-B マップの例:

![ADS-B マップ表示例](docs/images/adsb_map_example.png)

詳細な要件・アーキテクチャは `docs/` 以下にあります。
- `docs/architecture.md`
- `docs/adsb_amedas_requirements.md`

## 構成概要

- `src/`
  - `amedas_ingest.py`: AMeDAS 10 分値の最新版近傍を取得して `weather_amedas_10m` に UPSERT するバッチ
  - `amedas_backfill.py`: 過去にさかのぼって AMeDAS データを取得するバックフィル用スクリプト
  - `adsb_ingest.py`: dump1090-fa / SkyAware の `aircraft.json` を取得して `adsb_aircraft` に UPSERT するバッチ
- `sql/schema/`
  - `010_weather_site.sql` など、PostgreSQL のスキーマ定義と初期データ
- `docs/`
  - システムの要件・アーキテクチャ設計ドキュメント
- `.env.sample`
  - app_server 用の環境変数サンプル（実際の `.env` は Git 管理外）
- `.env.web.sample`
  - Django 開発用 Web ビューア（`web/adsb_viewer/`）が利用する DB 接続情報サンプル（実際の `.env.web` は Git 管理外）
- `config/`
  - 各ホストごとの設定を置くディレクトリ（実環境用のディレクトリは `.gitignore` 済み）
- `web/adsb_viewer/`
  - Django 4.2 系による ADS-B マップ用開発ビューア（`adsb_viewer.settings` では DB 名 `adsb_test`・ユーザ `lab_ro`・ホスト `127.0.0.1` を固定し、パスワードのみ環境変数 `PGPASSWORD` から参照）

## セットアップ手順（概要）

### 1. Python 環境の準備

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

※ 本リポジトリ直下の共通 `requirements.txt` には、DB 接続や Web ビューア開発に必要な主なライブラリ（`requests`, `psycopg2-binary`, `python-dateutil`, `Django` など）がまとまっています。追加のライブラリが必要な場合は、各自の環境に合わせて適宜インストールしてください。

### 2. `.env` の作成（app_server 側）

`adsb-amedas-lab` ルートにある `.env.sample` を元に、実環境用の `.env` を作成してください。

```bash
cp .env.sample .env
# .env を編集して、PGHOST などを自分の環境に合わせて設定
```

- `.env` は `.gitignore` により **Git 管理外** です。
- DB 接続情報やパスワードなどの機密情報は `.env` のみに記載してください。

### 3. 各 ADS-B ホスト用設定ディレクトリの作成

実環境の ADS-B ホスト用設定は、`config/` 以下にホストごとのディレクトリを作成し、その中に `env/` や `systemd/` を配置する想定です。

例（実際のホスト名に置き換えてください）:

```text
config/
  my_site1/
    env/
      adsb.env        # このファイルは Git 管理外にしてください
    systemd/
      adsb-ingest.service
      adsb-ingest.timer
  my_app_server/
    systemd/
      amedas-ingest.service
      amedas-ingest.timer
```

このリポジトリでは、実際の運用ホスト名を含む設定ディレクトリ（例: `config/rigel/`, `config/canopus/`）は **.gitignore によりリポジトリ外** としています。
そのため、公開リポジトリには **実ホスト名や個人の環境に依存する設定ファイルは含まれていません**。

利用する際は、上記のように自分の環境に合わせたディレクトリ名・パスで `config/<your_host>/` を作成し、その中に `env/adsb.env` や `systemd/` ファイルを用意してください。

- `env/adsb.env` は `.gitignore` のパターン `config/*/env/*.env` によって Git 管理外になります。
- systemd ユニットファイル内の `WorkingDirectory` や `User` なども、自分の環境に合わせて書き換えてください。

### 4. バッチ実行方法

開発用途で手動実行する場合の例です。

- AMeDAS 収集（app_server 上）:

```bash
dotenvx run -- python src/amedas_ingest.py
```

- ADS-B 収集（各 ADS-B ホスト上）:

```bash
dotenvx run -- env-file config/<your_site>/env/adsb.env -- python src/adsb_ingest.py
```

本番運用では、docs に記載のとおり `systemd service + timer` で定期実行することを想定しています。

### 5. 開発用 Web ビューア（Django adsb_viewer）

app_server 相当のホスト上で、PostgreSQL の `adsb_test.adsb_aircraft` を読み取り、直近の航空機位置を地図上に表示するための **開発用 Web ビューア** を Django で動かします。

補足（表示用 API の仕様）:

- `/api/latest/` は ADS-B データを JSON で返します。
  - クエリパラメータ:
    - `site`: 指定するとその `site_code` のみ
    - `limit`: 取得上限（ただし **1 site あたり最大 5000 件**に制限）
  - `site` を省略した場合は、DB 内の `site_code` それぞれについて **最新から `limit` 件ずつ**取得します。
    - 例: site が 2 つで `limit=5000` の場合、最大 10000 件になります。
- クライアント側（`adsb_map/templates/adsb_map/map.html`）では、取得した点群を `icao24` ごとにグルーピングし、軌跡を描画します。
  - 既定では、点数の多い軌跡（`icao24` グループ）上位のみを描画するため `TOP_K_TRACKS=100` を設定しています。
  - 軌跡の色は、時間方向（古い→新しい）を表現するため、軌跡内の点の並び（時系列ソート後の進行度）に応じて `d3.interpolateTurbo` のグラデーションを適用します。
  - データ欠損による不自然な直線補間を避けるため、連続点の時間差が一定値を超える区間は線を引かないようにしており、既定では `MAX_GAP_SEC=60`（60 秒超のギャップで分断）です。

#### 5.1 セットアップ（概要）

```bash
cd /path/to/adsb-amedas-lab/web/adsb_viewer

# 仮想環境を作成して有効化
python -m venv .venv
source .venv/bin/activate

# 依存パッケージをインストール（Django 4.2 / psycopg2-binary など）
pip install -r ../../requirements.txt

# Django 用の DB 接続情報サンプルから実ファイルを作成
cp ../../.env.web.sample ../../.env.web
# ../../.env.web を編集して、PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD を自分の環境に合わせて設定
```

- `web/adsb_viewer/adsb_viewer/settings.py` の `DATABASES["default"]` では、
  - 既定値として `NAME=adsb_test`, `USER=lab_ro`, `HOST=127.0.0.1`, `PORT=5432` を使い、
  - `PGDATABASE`, `PGUSER`, `PGHOST`, `PGPORT`, `PGPASSWORD` が設定されていればそれを優先します。
  - `PGPASSWORD` が未設定なら、libpq 標準の `~/.pgpass` フォールバックも利用できます。
- `run_dev_server.sh` はリポジトリルートの `.env.web` を `source` してから Django を起動するため、
  - `.env.web.sample` → `.env.web` を作成し、必要に応じて PG* 変数を設定してください。
  - スクリプト自身の配置場所からリポジトリルートを解決するため、クローン先は `~/adsb-amedas-lab` 固定である必要はありません。

#### 5.2 開発サーバの起動方法

- 手動起動（開発時）:

  ```bash
  cd /path/to/adsb-amedas-lab/web/adsb_viewer
  ./run_dev_server.sh
  ```

  - スクリプト内で `.env.web` を読み込み、`.venv` を有効化したうえで `python manage.py runserver 0.0.0.0:8000` を実行します。

- systemd 経由での自動起動（開発用）:

  - 例: `/etc/systemd/system/adsb-viewer.service`

    ```ini
    [Unit]
    Description=ADS-B Django viewer dev server
    After=network.target postgresql.service
    Wants=network-online.target

    [Service]
    Type=simple
    User=<your_user>
    Group=<your_user>
    WorkingDirectory=/path/to/adsb-amedas-lab/web/adsb_viewer
    ExecStart=/usr/bin/bash /path/to/adsb-amedas-lab/web/adsb_viewer/run_dev_server.sh
    Restart=on-failure
    Environment=PYTHONUNBUFFERED=1

    [Install]
    WantedBy=multi-user.target
    ```

  - 有効化・起動例:

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl enable --now adsb-viewer.service
    ```

  - 以降はホスト再起動後も `adsb-viewer.service` により Django ビューアが自動起動します。

#### 5.3 systemd 経由での制御例

```bash
# 起動 / 停止
sudo systemctl start adsb-viewer.service
sudo systemctl stop adsb-viewer.service

# ステータス確認
systemctl status adsb-viewer.service

# ログ末尾を確認
journalctl -u adsb-viewer.service -e

# 自動起動を無効化（かつ現在のサービスを停止）
sudo systemctl disable --now adsb-viewer.service
```

## 公開にあたっての注意点

- 実際のホスト名・ユーザ名・パスワードなどの機密情報は、`.env` や `config/*/env/*.env` のみに記載し、**Git にコミットしないでください**。
- 本リポジトリには、実運用用ディレクトリ（例: `config/rigel/`, `config/canopus/`）は含めていません。
  - `.gitignore` により、これらのディレクトリは自動的に無視されます。
- 公開リポジトリを fork / clone して利用する場合は、
  - 自分の環境用に `config/<your_host>/` ディレクトリを新規に作成
  - `.env.sample` を元に `.env` を作成
 する作業が別途必要になります。
