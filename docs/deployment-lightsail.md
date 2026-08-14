# Amazon Lightsail デプロイ

## 構成

- Amazon Lightsail Linux/Unix General Purpose（4GB RAM / 2 vCPU / 80GB SSD）
- 東京リージョン（`ap-northeast-1`）
- Caddy: Web UI配信とAPIリバースプロキシ
- Cloudflare Worker: 固定 `workers.dev` HTTPS URL
- Workers VPC / Cloudflare Tunnel: 公開ポートを使わないオリジン接続
- FastAPI: 内部ポート8000（インターネットへ直接公開しない）
- Worker: SQLiteジョブを処理し、Remotionを並列度1で実行
- Docker named volume: SQLite、音声、動画、中間成果物をAPIとWorkerで共有

## デモ環境

- 公開URL: `https://koebinar-demo.koebinar-demo-edge.workers.dev`
- Worker: `koebinar-demo`
- Tunnel: `koebinar-demo-origin` (`a3e89f29-74ef-4d70-b212-ac666f6c9cf6`)
- VPC Service: `koebinar-demo-web` (`019ffa4c-5b83-7bb1-9cd9-da1460231b79`)
- Lightsail: `koebinar-prod-1` / 静的IP `18.179.140.100`

公開URLは固定だが、`workers.dev`はCloudflare管理下のサブドメインであり、独自ドメイン
ではない。Cloudflare Workers VPCはベータ期間中の機能なので、本番移行前に提供条件と
料金を再確認する。

## IAMアクセス階層

IAM自体はグローバルサービスだが、各ポリシーでLightsail操作を東京リージョン
（`ap-northeast-1`）へ制限する。

| CLIプロファイル | IAMロール | 用途 |
| --- | --- | --- |
| `koebinar-viewer` | `KoebinarTokyoViewer` | 状態・構成の参照 |
| `koebinar-operator` | `KoebinarTokyoOperator` | 起動停止、再起動、スナップショット等の定常運用 |
| `koebinar-deployer` | `KoebinarTokyoDeployer` | 作成、変更、削除を含むデプロイ |

CLIは`koebinar-human`の一時認証から各ロールを引き受ける。ロールチェーンの制約に
より、CLIセッション時間は各プロファイルとも1時間とする。

## サーバー環境ファイル

`.env.production.example` を `.env.production` にコピーし、少なくとも次の値を
推測困難なランダム値へ変更する。

```dotenv
KOEBINAR_DEFAULT_AUTH_TOKEN=...
KOEBINAR_MASTER_KEY=...
KOEBINAR_SITE_ADDRESS=:80
CLOUDFLARE_TUNNEL_TOKEN=...
```

`.env.production` はGitへ追加しない。OrcaRouterとElevenLabsは認証付きIntegrations
APIからBYOKで登録するため、システム共通キーは既定で無効にする。

ローカルの`.env.production`を復旧用原本とし、権限600を維持する。単一テナント構成では
ログイン画面へワークスペースID`default`と`KOEBINAR_DEFAULT_AUTH_TOKEN`の値を入力する。
`KOEBINAR_TENANTS_JSON`を使う場合は、対象ワークスペースの`id`と`access_token`を入力する。

## 起動と確認

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1/api/v1/health/stack
```

Lightsailファイアウォールでは80/443番を公開しない。通常のデモアクセスは
`https://koebinar-demo.<account-subdomain>.workers.dev` から行い、障害調査時のみ
SSHトンネルを使う。

```bash
ssh -L 8080:127.0.0.1:80 ubuntu@LIGHTSAIL_STATIC_IP
```

ブラウザでは `http://127.0.0.1:8080` を開く。バックアップ対象は
`koebinar-data` volume。自動スナップショットは別料金のため、必要性と費用を確認して
から有効化し、重要なデモ前には手動スナップショットも取得する。

## ドメイン追加

DNSのAレコードをLightsail静的IPへ向け、`.env.production` の値を変更してWebだけを
再作成する。80/443番ポートの到達性があればCaddyが証明書を自動取得する。

```dotenv
KOEBINAR_SITE_ADDRESS=app.example.com
```

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d web
```

## Remotionライセンス

現デプロイは個人利用を前提とする。利用主体が4人以上になる前に、Remotionのその時点の
ライセンス条件を再確認し、必要な契約へ切り替える。
