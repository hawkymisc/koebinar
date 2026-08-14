# Koebinar（コエビナー）

> *あなたの声が、あなたの代わりに登壇する。*

企業の資料から、クローン音声ナレーション付きウェビナー動画（日英）を自動生成し、視聴中の質問にも資料の根拠付きで答える AI ウェビナーエージェント。

## ドキュメント

| ファイル | 内容 |
|---|---|
| `docs/audit_report.md` | 設計・仕様・実装・テストの現行整合性監査と不整合リスト |
| `docs/requirements.md` | 要件定義書 v1.8 |
| `docs/specification.md` | システム仕様書 v1.8 |
| `docs/tenant-auth-console.md` | テナント分離・ログイン・サイドバー・連携設定仕様 |
| `docs/article/koebinar-intro.md` | デモURL等の置換前に使う紹介記事ドラフト |

要件・仕様は目標契約、コードは現在の挙動、テストは明示的に検査した範囲の証拠として扱う。達成状況と既知の差分は `docs/audit_report.md` を参照。

## ローカル B スタック（推奨）

API / **永続 SQLite** / **成果物 FS** / **非同期パイプライン Worker** / **Remotion レンダ経路**。

```text
[Client] --HTTP--> [API :8000] --enqueue--> [SQLite jobs]
                         |                        |
                    metadata (SQLite)        [worker process]
                         |                        |
                    artifacts/  <---- outline..video / Remotion ----+
```

### 1. セットアップ

```bash
pip install -e ".[dev]"
# Remotion（任意だが推奨）
cd remotion && npm install && cd ..
```

### 2. 一括起動（API + Worker）

```bash
export KOEBINAR_DEFAULT_AUTH_TOKEN="$(openssl rand -hex 24)"
./scripts/start-stack.sh
# 別ターミナルで:
curl -s http://127.0.0.1:8000/api/v1/health/stack
```

ログ: `logs/api.log` / `logs/worker.log`  
停止: Ctrl+C

個別起動:

```bash
./scripts/start-api.sh      # port 8000
./scripts/start-worker.sh   # claims jobs, runs pipeline incl. video
```

Docker Compose 相当:

```bash
docker compose up --build
```

本番用（Web/Caddy + API + Worker）は `docker-compose.prod.yml` を使う。IP公開時は
`KOEBINAR_SITE_ADDRESS=:80`、ドメイン取得後はその値をホスト名へ変更するとCaddyが
HTTPSを自動設定する。詳細は `docs/deployment-lightsail.md` を参照。

### 3. 環境変数

| 変数 | 既定 | 意味 |
|---|---|---|
| `KOEBINAR_DB_PATH` | `storage/koebinar.db` | メタデータ SQLite（API/Worker 共有必須） |
| `KOEBINAR_ARTIFACTS_DIR` | `artifacts` | 中間生成物・MP4 |
| `KOEBINAR_SYNC_PIPELINE` | `false`（スタック時） | `true` で API 内同期実行（テスト向け） |
| `KOEBINAR_REMOTION_PROJECT_DIR` | `remotion` | Remotion プロジェクト |
| `KOEBINAR_FORCE_RENDER_DOUBLE` | `false` | `true` で Remotion を使わず double |
| `KOEBINAR_DEFAULT_AUTH_TOKEN` | なし（必須） | 運用者用Bearerトークン。公開フロントへ埋め込まない秘密値 |
| `KOEBINAR_TENANTS_JSON` | 空 | 複数ワークスペースの `id` / `name` / `access_token` JSON配列。設定時は単一トークン設定より優先 |
| `KOEBINAR_PUBLIC_QA_RATE_LIMIT` | `10` | 視聴者IP・ウェビナーごとのQ&A回数上限 |
| `KOEBINAR_PUBLIC_QA_RATE_WINDOW_SEC` | `60` | Q&A回数制限の時間窓（秒） |
| `KOEBINAR_MASTER_KEY` | dev 用 | BYOK 暗号化マスタ |

### 4. 非同期フロー

1. `POST /api/v1/webinars`（`auto_run=true`, `sync_pipeline=false`）→ `status=queued` + `job_id`（HTTP はすぐ返る）
2. Worker が job を claim → outline…video を実行
3. `GET /api/v1/webinars/{id}` で進捗・artifacts をポーリング
4. `GET /api/v1/webinars/{id}/jobs` / `GET /api/v1/jobs/{job_id}`

テストや同期デモでは body に `"sync": true` または `KOEBINAR_SYNC_PIPELINE=true`。

### 5. Remotion

- プロジェクト: `remotion/`（Composition `Webinar` + `render.mjs`）
- パイプライン Step 6 は `VideoRenderer` が Remotion を invoke
- 本番経路はRemotion失敗時にfail-closedとし、映像・音声ストリームと尺のprobeに合格したMP4だけを公開可能にする。`renderer=double`は明示的なテストモード専用で、`publishable=false`として扱う
- アダプタ境界はユニットテストで runner を差し替えて検証

```bash
# 手動 render 試行
cd remotion
node render.mjs --props /path/props.json --output /tmp/out.mp4
```

## Web UI（運用者コンソール + 公開視聴ページ）

React（Vite）製。運用者コンソールではウェビナー作成、進捗確認、台本編集、ステップ再実行、動画プレビュー、公開操作を行う。完成後に明示的に公開すると、APIトークンを表示しない `/watch/{id}` の視聴者専用ページで動画再生と根拠付きQ&Aを利用できる。

```bash
./scripts/start-web.sh
# または
cd web && npm install && npm run dev
```

起動前に `KOEBINAR_DEFAULT_AUTH_TOKEN` を推測困難な秘密値に設定する。`http://localhost:5173` を開き、ログイン画面でワークスペースID `default` と同じトークンを入力する。複数テナントでは `KOEBINAR_TENANTS_JSON` を使う。API既定は `http://127.0.0.1:8000/api/v1`（`web/.env` の `VITE_API_BASE` で変更可）。トークンに既定値はなく、公開フロントのJavaScriptには埋め込まれない。詳細は `docs/tenant-auth-console.md` を参照。

APIサーバー側は `CORSMiddleware`（`allow_origins=["*"]`, Bearerトークン運用でCookie未使用のため許容）でdevサーバーからのアクセスを許可している。

## 実装構成

```
src/koebinar/
  api/           # REST /api/v1
  jobs.py        # SQLite job queue
  worker.py      # pipeline worker CLI (koebinar-worker)
  storage.py     # durable SQLite + FS artifacts
  knowledge/ integrations/ llm/ pipeline/ qa/
remotion/        # Remotion project + render.mjs
web/             # 運用者コンソール + 視聴者Q&A（Vite + React + TypeScript）
scripts/         # start-api / start-worker / start-stack / start-web
tests/           # unit + ≥100 E2E（モック）
```

## テスト / カバレッジ

```bash
pytest tests -q --cov=koebinar --cov-branch --cov-report=term
pytest tests/e2e -q

cd web
npm test
PLAYWRIGHT_BROWSERS_PATH=0 npx playwright install chromium
npm run test:e2e
```

外部 LLM/TTS は **API 互換モック**（`tests/mocks/providers.py`）。実 API キー不要。  
テスト既定は `sync_pipeline=True` + render double（高速・決定的）。
Playwright E2EだけはローカルのAPI互換モックと**実Remotionレンダリング**を使い、資料アップロードからH.264 MP4のブラウザ再生まで検証する。ブラウザ検査自体はmuteで行うが、レンダラーの統合テストと`ffprobe`契約で映像・音声ストリームと尺を別途検証する。

## 主要 API

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/v1/health` | 生存確認 |
| GET | `/api/v1/health/stack` | B スタック状態（db / jobs / sync フラグ） |
| POST | `/api/v1/knowledge/documents` | 資料登録 |
| POST | `/api/v1/webinars` | ジョブ作成（async/sync） |
| GET | `/api/v1/webinars` | ウェビナー一覧（新しい順） |
| GET | `/api/v1/webinars/{id}` | 状態・中間生成物 |
| GET | `/api/v1/webinars/{id}/jobs` | 関連ジョブ一覧 |
| GET | `/api/v1/jobs/{id}` | ジョブ詳細 |
| PATCH | `/api/v1/webinars/{id}/script` | 台本修正 |
| POST | `/api/v1/webinars/{id}/steps/{step}/run` | ステップ再実行（`?sync=` 可） |
| GET | `/api/v1/webinars/{id}/video` | MP4 取得 |
| PATCH | `/api/v1/webinars/{id}/publication` | 視聴者ページの公開・停止 |
| GET | `/api/v1/public/webinars/{id}` | 公開ウェビナーの最小メタデータ（認証不要） |
| GET | `/api/v1/public/webinars/{id}/video` | 公開MP4（認証不要） |
| POST/GET | `/api/v1/public/webinars/{id}/questions` | 公開ページの質問・回答（認証不要） |
| POST/GET/DELETE | `/api/v1/integrations/{provider}` | BYOK |
| GET | `/api/v1/integrations/elevenlabs/voices` | Voice 一覧 |
| POST/GET | `/api/v1/questions` | 運用者用 Q&A（認証必須） |
| GET | `/api/v1/analytics/questions` | 質問エクスポート |

運用者API認証: `Authorization: Bearer <tenant access_token>`。単一テナント構成では `KOEBINAR_DEFAULT_AUTH_TOKEN` が `default` ワークスペースの `access_token` になる。

公開Q&Aの回数制限は、APIが認識するクライアントIPとウェビナーIDを単位にする。リバースプロキシ配下では、Uvicornの `--forwarded-allow-ips` に実際のプロキシIPだけを設定すること。無条件に転送ヘッダーを信頼しない。

## Version

- App: 0.3.0 (B-stack + Remotion path + Web UI)
- Spec docs: v1.8
