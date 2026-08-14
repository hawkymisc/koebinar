# Koebinar Web UI

Vite + React + TypeScriptで実装したKoebinarの運用者コンソールと公開視聴ページ。

## 提供画面

- `/login`: ワークスペースIDとアクセストークンによるログイン
- `/`: PDF/PPTX/TXT/Markdown資料のブラウザ内抽出、資料選択、ウェビナー作成・一覧
- `/webinars/{id}`: 進捗確認、台本編集、ステップ再実行、動画プレビュー、公開操作
- `/settings/integrations`: OrcaRouter / ElevenLabsのテナント別BYOK設定とVoice一覧
- `/watch/{id}`: 認証不要の公開動画・根拠付きQ&A

既知の設計・実装差分は [`docs/audit_report.md`](../docs/audit_report.md) を参照。特に、Voice一覧は現時点でウェビナー作成フォームの選択値へ接続されていない。

## ローカル起動

先にリポジトリルートでAPIとWorkerを起動する。

```bash
export KOEBINAR_DEFAULT_AUTH_TOKEN="$(openssl rand -hex 24)"
./scripts/start-stack.sh
```

別ターミナルでWeb UIを起動する。

```bash
cd web
npm install
npm run dev
```

既定APIは`http://127.0.0.1:8000/api/v1`。変更する場合は`web/.env`等で指定する。

```dotenv
VITE_API_BASE=http://127.0.0.1:8000/api/v1
```

単一テナント構成では、ログイン画面へワークスペースID`default`と`KOEBINAR_DEFAULT_AUTH_TOKEN`の値を入力する。トークンはブラウザの`localStorage`へ保存され、運用者APIのBearer tokenとして送信される。公開視聴APIへは送信しない。

## テスト

```bash
npm test
npm run lint
npm run build
npm run test:e2e
```

`test:e2e`は`web/playwright.config.ts`から一時APIとViteを起動する。Python仮想環境`.venv`、Playwright Chromium、Remotion依存が必要。外部APIはローカル互換モックを使い、実Remotion映像のブラウザ再生を検証する。ブラウザ検査はmuteだが、バックエンドのrenderer統合テストと`ffprobe`契約が映像・音声ストリームと尺を検証する。
