# ADS-B + AMeDAS Lab System Architecture

_Revision: 2025-12-07_

このドキュメントは、ADS-B 受信データと AMeDAS 気象データを収集し、PostgreSQL に保存するラボ環境の構成を、ホスト名やサイト名を一般化した形でまとめたものです。

実際のホスト名・サイト名・パスワード・IP アドレスなどの固有情報は、すべて `.env` / `*.env` に集中させ、リポジトリにはコミットしない運用とします。

---

## 1. ロールとホスト構成

1. **app_server**
   - 役割:
     - 中央 PostgreSQL サーバ
     - AMeDAS 収集バッチの実行
     - Git リポジトリ `adsb-amedas-lab` の配置
   - 主なコンポーネント:
     - PostgreSQL データベース `adsb_test`
     - Python ランタイム（venv）
     - dotenvx
     - systemd で AMeDAS バッチをタイマー実行

2. **site1_host / site2_host / ...**
   - 役割:
     - 各 ADS-B 受信拠点（例: ラズパイ + SDR）
   - 主なコンポーネント:
     - dump1090-fa / readsb / SkyAware などの ADS-B デコーダ
     - `adsb-amedas-lab` コード（app_server から rsync or git clone）
     - Python ランタイム（venv）
     - dotenvx
     - systemd で ADS-B インジェストを 5 秒周期で実行

3. **ネットワーク前提**
   - app_server と siteN_host は、
     - ローカルネットワーク (例: `192.168.x.x`) または
     - Tailnet (Tailscale)
     経由で PostgreSQL ポートに到達できること。
   - PostgreSQL の `pg_hba.conf` では、以下のみを許可する運用を想定:
     - 内部ネットワークセグメント
     - Tailnet アドレス範囲

---

## 2. データフロー概要

1. **AMeDAS**
   1. app_server 上の `amedas_ingest.py` が、気象庁の AMeDAS API から指定地点の 10 分値を取得。
   2. AMeDAS 観測所メタ情報 `weather_site` を参照しつつ、観測値を `weather_amedas_10m` に UPSERT。
   3. systemd timer により、10 分ごと程度で自動実行。

2. **ADS-B**
   1. 各 siteN_host 上の `adsb_ingest.py` が、ローカルの SkyAware 等から `aircraft.json` を取得。
      - 例: `http://localhost/skyaware/data/aircraft.json`
   2. JSON から航空機ごとの状態を抽出し、サイト識別子（例: `site1`, `site2`）とともに `adsb_aircraft` に UPSERT。
   3. siteN_host 上の systemd timer により、5 秒間隔で自動実行。

---

## 3. データベーススキーマ

### 3.1 共通

- データベース名: `adsb_test`（ラボ用）
- ロール:
  - `dbuser`: 管理・スキーマ作成用
  - `lab_rw`: アプリケーションからの読み書き用
  - `lab_ro`: 読み取り専用クエリ用

### 3.2 `weather_site`

AMeDAS 観測所のメタデータを保持。

- 主キー: `amedas_id`
- 主なカラム:
  - `amedas_id` (text)
  - `name` (text)
  - `region` (text)
  - 緯度経度など（必要に応じて拡張）

### 3.3 `weather_amedas_10m`

AMeDAS の 10 分値。

- 主キー: `(amedas_id, obs_time)`
- 主なカラム:
  - `amedas_id` (text) — `weather_site.amedas_id` に対応
  - `obs_time` (timestamptz) — JST での観測時刻（DB的には timestamptz）
  - `temp` (numeric or double precision)
  - `precip_10m` (numeric or double precision) — 10 分降水量
  - `wind_speed` (numeric or double precision)
  - `wind_dir` (integer)
  - `raw` (jsonb) — 元 JSON の該当レコード全体

### 3.4 `adsb_aircraft`

ADS-B の航空機ごとのスナップショット。

- テーブル構造:
  - 親テーブル `adsb_aircraft` は `snapshot_time` で RANGE パーティショニング。
  - 実データは月単位などで子パーティションに格納。
- 主なカラム:
  - `id` (bigint, identity, PK)
  - `site_code` (text) — 受信拠点を表す論理名（例: `site1`, `site2`）
  - `snapshot_time` (timestamptz) — JSON 取得時刻（UTC）
  - `icao24` (text) — 24-bit ICAO address
  - `flight` (text)
  - `squawk` (text)
  - `lat` / `lon` (double precision)
  - `alt_baro` (integer)
  - `gs` (double precision) — ground speed
  - `track` (double precision)
  - `raw` (jsonb) — 元 JSON の aircraft 要素全体
- 一意制約:
  - `UNIQUE (site_code, snapshot_time, icao24)`
    - 同じサイト・同じスナップショット・同一機体は 1 行に集約。

---

## 4. バッチ / サービス構成

### 4.1 AMeDAS (app_server)

1. **環境変数 (.env)**

   - 例:

     ```dotenv
     PGHOST=app_server_host
     PGPORT=5432
     PGDATABASE=adsb_test
     PGUSER=lab_rw
     PGPASSWORD=...  # 非公開

     AMEDAS_IDS=44132,45401,46106
     ```

2. **Python スクリプト**

   - `src/amedas_ingest.py`
     - 最新値（直近 3 時間程度）を取得して UPSERT。
   - `src/amedas_backfill.py`
     - 過去にさかのぼってブロック単位で取得。

3. **systemd timer**

   - 例: `amedas-ingest.service` / `amedas-ingest.timer`
   - `dotenvx run -- python3 src/amedas_ingest.py` を定期実行。

### 4.2 ADS-B (siteN_host)

1. **環境変数 (config/siteN/env/adsb.env)**

   - 例 (`config/site1/env/adsb.env`):

     ```dotenv
     PGHOST=app_server_host
     PGPORT=5432
     PGDATABASE=adsb_test
     PGUSER=lab_rw
     PGPASSWORD=...  # 非公開

     ADS_SITE_CODE=site1
     ADS_JSON_URL=http://localhost/skyaware/data/aircraft.json
     ```

2. **Python スクリプト**

   - `src/adsb_ingest.py`
     - `ADS_JSON_URL` から JSON を取得。
     - 各 aircraft エントリを行に展開。
     - `adsb_aircraft` に UPSERT。

3. **systemd timer**

   - 例: `adsb-ingest.service` / `adsb-ingest.timer`
   - `dotenvx run -- python3 src/adsb_ingest.py` を 5 秒間隔で実行。

---

## 5. 環境変数と公開範囲のポリシー

1. **リポジトリに含めるもの**
   - `.env.sample`（app_server 用）
   - `config/siteN/env/adsb.env.sample`（各サイト用）
   - systemd ユニットファイル（ホスト名・パスは一般化するか、`%h` 等で抽象化）

2. **リポジトリに含めないもの**
   - `.env`
   - `config/siteN/env/*.env`
   - 実際のホスト名・IP・パスワード・Tailnet 名称

3. **命名の方針**
   - 公開ドキュメントでは、
     - app_server
     - site1_host / site2_host
     - site1 / site2 (site_code)
   - 実環境では、より意味のある名前を用いて `.env` 側で紐付ける。

---

## 6. 今後の拡張想定

1. **アプリケーションサーバ**
   - app_server 上、または別ホスト上に Web アプリを立て、
     - 地図上のフライトトラッキング
     - 天気（AMeDAS）とのオーバーレイ
     - 過去 n 時間〜月・年単位でのリプレイ表示
     を実装する計画。

2. **サイトの追加**
   - 新しい ADS-B 拠点を追加する場合は、
     1. `config/siteX/env/adsb.env.sample` をコピーして編集
     2. siteX_host にコードと systemd ユニットをデプロイ
     3. `ADS_SITE_CODE=siteX` として `adsb_aircraft.site_code` に識別させる

3. **本番 DB への移行**
   - 現在の `adsb_test` を元に、将来的に別ホストの本番 DB に移行予定。
   - その際も、接続先の変更は `.env` 側で吸収し、コードとスキーマは共通とする。

---

## 7. Web ビューア (Django 開発用)

本節では、app_server 相当のホスト上で Django を使った ADS-B + AMeDAS 開発用 Web ビューアを動かすための構成メモをまとめる。実際のホスト名・ユーザ名・パスワード・IP アドレスなどは `.env` 等に保持し、ここでは一般化した名称のみを記載する。

### 7.1 全体像

- ホスト: app_server 相当の Linux ホスト (例: AlmaLinux 9 系)
- DB: PostgreSQL (DB 名: `adsb_test`)
- Web: Django 4.2 系
  - プロジェクト: `adsb_viewer`
  - アプリ: `adsb_map`
- ロール:
  - `lab_ro`: 読み取り専用クエリ用ロール
- 用途:
  - `adsb_test.adsb_aircraft` の最新データを取得し、地図上に表示するための **開発用ビューア**。

### 7.2 Django プロジェクト / 仮想環境構成

#### 7.2.1 ディレクトリ構成 (例)

```text
~/adsb-amedas-lab/
  web/
    adsb_viewer/
      .venv/
      adsb_viewer/   # Django プロジェクト本体 (settings.py など)
      adsb_map/      # ADS-B ビューア用アプリ
      manage.py
      run_dev_server.sh
```

#### 7.2.2 仮想環境と Django インストール (参考)

```bash
cd /path/to/adsb-amedas-lab/web/adsb_viewer

python3 -m venv .venv
source .venv/bin/activate

# Django 4.2 系 (Python 3.9 互換)
pip install "Django>=4.2,<5.0" "psycopg2-binary>=2.9"
```

#### 7.2.3 Django プロジェクトとアプリ作成 (参考)

既存環境ではすでに作成済みだが、セットアップ手順の参考として残しておく。

```bash
cd /path/to/adsb-amedas-lab/web/adsb_viewer
source .venv/bin/activate

django-admin startproject adsb_viewer .
python manage.py startapp adsb_map
```

### 7.3 PostgreSQL 認証まわりの調整 (概要)

詳細なロール構成は 3 章を参照。ここでは Django 開発サーバからの接続に必要なポイントだけを整理する。

#### 7.3.1 読み取り専用ロールのパスワード設定

管理ロール (例: `dbuser` や `postgres`) でログインし、`lab_ro` にログイン可能なパスワードを設定する。

```sql
ALTER ROLE lab_ro WITH LOGIN PASSWORD '<strong-password-here>';
```

実際のパスワード文字列はリポジトリに書かず、`.env` やホスト固有の秘密情報として管理する。

#### 7.3.2 `pg_hba.conf` の設定 (localhost からの接続許可)

`pg_hba.conf` の場所は次のように確認できる:

```bash
sudo -u postgres psql -c 'SHOW hba_file;'
```

該当ファイルに、既存の内部ネットワーク向けルールに加えて、Django 開発サーバ用の localhost (IPv4) 経由のルールを追加する:

```text
# Local connections (Unix domain socket)
local   all         postgres                                peer
local   all         all                                     md5

# app_server 内部ネットワーク / Tailnet 向けのルール (例)
host    all         lab_rw     192.168.x.0/24               md5
host    all         lab_ro     192.168.x.0/24               md5
host    all         lab_rw     100.64.0.0/10                md5
host    all         lab_ro     100.64.0.0/10                md5

# Django 開発サーバ用 (app_server ローカル 127.0.0.1 → adsb_test を lab_ro で)
host    adsb_test   lab_ro     127.0.0.1/32                 md5

# その他のリモート接続はデフォルト拒否とするポリシー例
host    all         all        0.0.0.0/0                    reject
```

変更後は PostgreSQL サービスをリロードする:

```bash
sudo systemctl reload postgresql      || \
sudo systemctl reload postgresql-13   || \
sudo systemctl reload postgresql-16
```

#### 7.3.3 接続確認

開発ユーザシェルから、`.venv` を有効化した上で次のように接続確認を行う:

```bash
cd /path/to/adsb-amedas-lab/web/adsb_viewer
source .venv/bin/activate

PGPASSWORD='<strong-password-here>' \
  psql -h 127.0.0.1 -U lab_ro -d adsb_test -c "SELECT now();"
```

これが成功すれば、同じ条件で Django からも DB に接続できる前提が整う。

### 7.4 Django 設定 (DB / ネットワーク)

#### 7.4.1 INSTALLED_APPS

`adsb_viewer/settings.py` の一部抜粋:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "adsb_map",  # ADS-B ビューア用アプリ
]
```

#### 7.4.2 ALLOWED_HOSTS (開発用)

開発中は外部端末からのアクセスを許可するため、一時的にワイルドカードを利用している例:

```python
ALLOWED_HOSTS = ["*"]
```

本番運用では、実際のホスト名やドメインに絞り込むことを推奨。

#### 7.4.3 DATABASES

DB 接続情報は `.env` などから環境変数として受け取り、未設定時はローカル開発向け既定値にフォールバックする運用を想定する。

```python
import os


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("PGDATABASE", "adsb_test"),
        "USER": os.environ.get("PGUSER", "lab_ro"),
        "HOST": os.environ.get("PGHOST", "127.0.0.1"),  # 開発時は IPv4 ループバックを利用
        "PORT": os.environ.get("PGPORT", "5432"),
    }
}

pg_password = os.environ.get("PGPASSWORD")
if pg_password:
    DATABASES["default"]["PASSWORD"] = pg_password
```

### 7.5 開発用サーバ起動スクリプト

#### 7.5.1 `run_dev_server.sh`

app_server 上で Django 開発サーバを簡単に再起動できるよう、次のようなシェルスクリプトを用意しておく。実装例（本リポジトリ同梱のファイル）は以下のとおり:

```bash
#!/usr/bin/env bash
# Simple restart script for ADS-B Django dev server

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
ENV_WEB_FILE="$REPO_ROOT/.env.web"
VENV_ACTIVATE="$SCRIPT_DIR/.venv/bin/activate"

cd "$SCRIPT_DIR"

if [ -f "$ENV_WEB_FILE" ]; then
    set -a
    . "$ENV_WEB_FILE"
    set +a
fi

if [ ! -f "$VENV_ACTIVATE" ]; then
    echo "Missing virtual environment: $VENV_ACTIVATE" >&2
    echo "Create it with: python3 -m venv \"$SCRIPT_DIR/.venv\" && \"$SCRIPT_DIR/.venv/bin/pip\" install -r \"$REPO_ROOT/requirements.txt\"" >&2
    exit 1
fi

. "$VENV_ACTIVATE"
exec python manage.py runserver 0.0.0.0:8000
```

- `.env.web.sample` をリポジトリルートに用意し、実際の接続情報は `.env.web` にのみ記載する運用とする。
- `adsb_viewer/settings.py` 側では、
  - `NAME="adsb_test"` / `USER="lab_ro"` / `HOST="127.0.0.1"` / `PORT="5432"` を既定値とし、
  - `PGDATABASE` / `PGUSER` / `PGHOST` / `PGPORT` / `PGPASSWORD` があればそれを優先し、
  - `PGPASSWORD` が無ければ `~/.pgpass` を含む libpq 標準の認証経路を使う。
  これにより、Web ビューアは読み取り専用ロール `lab_ro` で DB に接続する。

権限付与例:

```bash
cd /path/to/adsb-amedas-lab/web/adsb_viewer
chmod +x run_dev_server.sh
```

#### 7.5.2 手動起動とログ

```bash
cd /path/to/adsb-amedas-lab/web/adsb_viewer
./run_dev_server.sh
```

正常起動例:

```text
Watching for file changes with StatReloader
Performing system checks...

System check identified no issues (0 silenced).
December xx, 2025 - HH:MM:SS
Django version 4.2.xx, using settings 'adsb_viewer.settings'
Starting development server at http://0.0.0.0:8000/
Quit the server with CONTROL-C.
```

この方法では、シェルセッションを閉じると Django 開発サーバも停止する。

#### 7.5.3 systemd による自動起動 (`adsb-viewer.service`)

開発中でもホスト再起動後に自動で Django ビューアを立ち上げたい場合、`run_dev_server.sh` をラップする systemd サービスを用意しておくと便利である。例:

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

有効化・起動例:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now adsb-viewer.service
```

この設定により、ホストを再起動しても `adsb-viewer.service` が自動的に Django 開発サーバを起動する。

主な制御コマンド例:

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

### 7.6 Firewalld で 8000/tcp を外部向けに開放 (開発用)

app_server 上で firewalld が有効な場合、Django 開発サーバに外部端末からアクセスするには 8000/tcp を開放する必要がある。

#### 7.6.1 firewalld の状態確認

```bash
sudo firewall-cmd --state
```

`running` の場合はポート設定を確認する。

#### 7.6.2 8000/tcp の恒久開放 (開発用の例)

```bash
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload

sudo firewall-cmd --list-ports  # 8000/tcp が含まれていれば OK
```

本番運用では、リバースプロキシ (例: Nginx) 経由で 80/443 のみを公開し、Django は内部ポートで待ち受ける構成を推奨する。

### 7.7 クライアント側からの動作確認

#### 7.7.1 app_server ローカルからの確認

```bash
curl -I http://localhost:8000/
```

`HTTP/1.1 200 OK` が返ってくれば、少なくともローカルからの疎通は問題ない。

#### 7.7.2 LAN クライアントからの確認

LAN 上の別ホストから、app_server のホスト名または IP を指定してアクセスする:

```bash
curl -I http://<app_server_hostname>:8000/
```

成功例:

```text
HTTP/1.1 200 OK
...
```

ブラウザから `http://<app_server_hostname>:8000/` を開き、ADS-B マップ画面が表示されることを確認する。

### 7.8 現状の Web ビューアの表示仕様メモ

本リポジトリに含まれる Django 開発用 Web ビューアでは、現状おおむね次のような表示仕様として実装している。

- `/api/latest/` から取得する ADS-B データは、クエリパラメータにより以下の挙動となる。
  - `site` 指定あり: 指定 site の `site_code` のみを対象に、最新から `limit` 件を返す。
  - `site` 指定なし: DB 内の `site_code` ごとに、最新から `limit` 件ずつを返す。
  - `limit` は **1 site あたり最大 5000 件**にクランプする。
- クライアント側では Leaflet による地図表示の上に、取得した点群を `icao24` ごとにグルーピングして軌跡を描画している。
  - 既定では視認性のため、点数が多い軌跡（`icao24` グループ）上位のみを描画する (`TOP_K_TRACKS=100`)。
  - 軌跡の色は、時間方向（古い→新しい）を表現するため、軌跡内の点の並び（時系列ソート後の進行度）に応じて `d3-scale-chromatic` の `interpolateTurbo` を適用する。
  - データ欠損による不自然な直線補間を避けるため、連続点の時間差が一定値を超える区間は線を引かないようにしており、既定では `MAX_GAP_SEC=60`（60 秒超のギャップで分断）とする。
- 各機体については、**最新点のみマーカーを表示**し、便名 (`flight`) が空の機体についてはマーカーを出さず、軌跡のみ表示することで視認性を確保している。

今後、時間フィルタやサイト切り替え UI、自動リロードなどを追加する場合も、ここで述べた方針（DB 側は `adsb_aircraft` の読み取り専用、可視化ロジックはあくまでクライアント側で完結させる）を基本とする。
