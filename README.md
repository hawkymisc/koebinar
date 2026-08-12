# Koebinar（コエビナー）

> *あなたの声が、あなたの代わりに登壇する。*

企業の資料から、クローン音声ナレーション付きウェビナー動画（日英）を自動生成し、視聴中の質問にも資料の根拠付きで答える AI ウェビナーエージェント。

## ドキュメント

| ファイル | 内容 |
|---|---|
| `docs/audit_report.md` | v1.0 監査結果 |
| `docs/requirements.md` | 要件定義書 v1.5 |
| `docs/specification.md` | システム仕様書 v1.5 |

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

### 3. 環境変数

| 変数 | 既定 | 意味 |
|---|---|---|
| `KOEBINAR_DB_PATH` | `storage/koebinar.db` | メタデータ SQLite（API/Worker 共有必須） |
| `KOEBINAR_ARTIFACTS_DIR` | `artifacts` | 中間生成物・MP4 |
| `KOEBINAR_SYNC_PIPELINE` | `false`（スタック時） | `true` で API 内同期実行（テスト向け） |
| `KOEBINAR_REMOTION_PROJECT_DIR` | `remotion` | Remotion プロジェクト |
| `KOEBINAR_FORCE_RENDER_DOUBLE` | `false` | `true` で Remotion を使わず double |
| `KOEBINAR_DEFAULT_AUTH_TOKEN` | `mvp-token` | Bearer トークン |
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
- headless Chromium が使えない環境では **同じ entry** が double MP4（ftyp/mdat）にフォールバック
- アダプタ境界はユニットテストで runner を差し替えて検証

```bash
# 手動 render 試行
cd remotion
node render.mjs --props /path/props.json --output /tmp/out.mp4
```

## Web UI（運用者コンソール + 視聴者Q&A）

React（Vite）製。ウェビナー作成、進捗確認、台本編集、ステップ再実行、動画プレビュー、視聴者Q&Aを1画面で行う。

```bash
./scripts/start-web.sh
# または
cd web && npm install && npm run dev
```

`http://localhost:5173` を開く。API既定は `http://127.0.0.1:8000/api/v1`（`web/.env` の `VITE_API_BASE` で変更可）。認証トークンは画面右上の入力欄で設定（既定 `mvp-token`、`localStorage` に保存）。

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
```

外部 LLM/TTS は **API 互換モック**（`tests/mocks/providers.py`）。実 API キー不要。  
テスト既定は `sync_pipeline=True` + render double（高速・決定的）。

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
| POST/GET/DELETE | `/api/v1/integrations/{provider}` | BYOK |
| GET | `/api/v1/integrations/elevenlabs/voices` | Voice 一覧 |
| POST/GET | `/api/v1/questions` | 視聴者 Q&A |
| GET | `/api/v1/analytics/questions` | 質問エクスポート |

認証: `Authorization: Bearer mvp-token`

## Version

- App: 0.3.0 (B-stack + Remotion path + Web UI)
- Spec docs: v1.6
