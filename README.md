# Koebinar（コエビナー）

> *あなたの声が、あなたの代わりに登壇する。*

企業の資料から、クローン音声ナレーション付きウェビナー動画（日英）を自動生成し、視聴中の質問にも資料の根拠付きで答える AI ウェビナーエージェント。

## ドキュメント

| ファイル | 内容 |
|---|---|
| `docs/audit_report.md` | v1.0 監査結果 |
| `docs/requirements.md` | 要件定義書 v1.5 |
| `docs/specification.md` | システム仕様書 v1.5 |

## 実装（Phase 1 MVP）

Python / FastAPI による API + 生成パイプライン。

```
src/koebinar/
  api/           # REST /api/v1
  knowledge/     # 資料登録・chunk・検索
  integrations/  # BYOK (OrcaRouter / ElevenLabs)
  llm/           # OpenAI 互換クライアント
  pipeline/      # outline→…→video オーケストレーション
  qa/            # RAG Q&A + confidence gate
tests/
  mocks/         # API 互換モック (respx)
  unit/ e2e/     # 単体 + 100+ E2E シナリオ
```

### セットアップ

```bash
pip install -e ".[dev]"
```

### 起動

```bash
# 既定トークン: mvp-token
uvicorn koebinar.main:create_app --factory --host 0.0.0.0 --port 8000
```

### テスト / カバレッジ

```bash
# 全テスト + C0/C1 (statement + branch)
pytest tests -q --cov=koebinar --cov-branch --cov-report=term

# E2E のみ
pytest tests/e2e -q
```

外部 LLM / TTS は **API 互換モック**（`tests/mocks/providers.py`）を使用。実 API キー不要。

### 主要 API

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/v1/knowledge/documents` | 資料登録 |
| POST | `/api/v1/webinars` | ジョブ作成（auto_run 可） |
| GET | `/api/v1/webinars/{id}` | 状態・中間生成物 |
| PATCH | `/api/v1/webinars/{id}/script` | 台本修正 |
| POST | `/api/v1/webinars/{id}/steps/{step}/run` | ステップ再実行 |
| GET | `/api/v1/webinars/{id}/video` | MP4 取得 |
| POST/GET/DELETE | `/api/v1/integrations/{provider}` | BYOK |
| GET | `/api/v1/integrations/elevenlabs/voices` | Voice 一覧 |
| POST/GET | `/api/v1/questions` | 視聴者 Q&A |
| GET | `/api/v1/analytics/questions` | 質問エクスポート |

認証: `Authorization: Bearer mvp-token`（`KOEBINAR_DEFAULT_AUTH_TOKEN` で変更可）

### レンダラについて

本環境では Remotion headless が使えないため、パイプライン境界で **honest double** が `webinar.mp4`（ISO BMFF 風 ftyp/mdat + タイムラインメタ）を出力する。タイムライン計算・成果物永続化は本番と同じ経路を通る。

## Version

- App: 0.1.0
- Spec docs: v1.5
- 2026-08-08
