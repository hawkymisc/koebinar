# 設計・仕様・実装・テスト 整合性監査レポート

| 項目 | 内容 |
|---|---|
| 監査日 | 2026-08-15 |
| 基準コミット | `11f73a5`（`origin/main`）+ `fix/elevenlabs-key-validation` 作業差分 |
| 対象 | `README.md`、`docs/`、API、Worker、Web UI、Remotion、テスト、Compose設定 |
| 判定 | **部分整合**。Issue #12〜14の変更範囲はClean。リポジトリ全体には既報の未解消不整合が残る |
| 未解消 | Critical 0件 / High 3件 / Medium 7件 / Low 3件（計13件） |
| 解消済み | Critical 3件（A-001、A-002、A-005） |

## 1. 文書の位置づけ

- `requirements.md`: プロダクト要件と受入条件の正本
- `specification.md`: 要件を実現する技術契約の正本
- 実装・構成ファイル: 現在の実際の挙動
- テスト結果: テストが明示的に検証した範囲だけの達成証拠
- 本書: 上記4層の差分と未検証事項を記録する現行監査

テスト通過だけでは仕様達成と判定しない。テストが受入条件を直接検査しているか、テストダブルではなく必要な実経路を通っているかまで確認した。

### 1.1 監査対象外

- ローカル生成物としてGit管理対象外にした `site/`
- AWS Lightsail / Cloudflare の現在の稼働状態と設定値
- OrcaRouter / ElevenLabs の契約、料金、利用規約の最新内容
- 実アカウントを使う外部APIの品質・残高・レート上限

## 2. 検証結果

| 検証 | 結果 | 証明する範囲 |
|---|---|---|
| `.venv/bin/pytest tests -q --cov=koebinar --cov-branch --cov-report=term` | **301 passed**、分岐込み **90.32%** | Pythonの単体・API・モックE2E。実プロバイダーの音声品質は対象外 |
| `cd web && npm test` | **21 passed** | APIクライアント、認証UI、権限ヒント、Voice同意、ファイル抽出の単体契約 |
| `cd web && npm run build` | **pass** | TypeScript型検査とVite本番ビルド |
| `cd web && npm run lint` | **pass** | Oxlint静的検査 |
| `cd web && npm run test:e2e` | **今回未再実行**（前回監査: 1 passed） | 今回は生成・動画経路を変更していない。前回は実Remotionによる1920×1080 H.264映像のブラウザ再生、公開導線、Q&Aを検証 |

Pythonテストは成功したが、SQLite接続未解放の `ResourceWarning` を中心に226件のwarningが出た（既報A-016）。

### 2.1 Issue #12〜14 差分監査

| 受入契約 | 実装証拠 | テスト証拠 | 判定 |
|---|---|---|---|
| 登録時の外部プロバイダー401/403等をKoebinar認証401と分離 | `IntegrationsService._validate_orcarouter/_validate_elevenlabs` が安全なdetailの422へ正規化 | service/API/Web client回帰テスト | Clean |
| 検証失敗時にセッションと既存integrationを維持し、秘密情報を返さない | 保存は検証成功後のみ。Webは422で`clearSession`を実行しない | 401/403/429/500、既存record、localStorage、レスポンス非漏えいを検証 | Clean |
| OrcaRouter / ElevenLabsの必要アクセス範囲を一貫したUIで案内 | 両カードにnative `details/summary`の`[i]`ヒント、モバイル用viewport内配置 | 文言、要素数、ARIA名、本番build、lintを検証 | Clean |
| 要件・仕様・運用コンソール文書との整合 | requirements/specificationをv1.9、tenant-auth-consoleをv1.1へ更新 | 実装・テスト・3文書を相互照合 | Clean |
| TTS + Voices ReadのみのElevenLabsキーを登録可能 | Voice一覧を必須検証、User Readを使うSubscription照会を任意化し取得不能警告を保存 | Subscription 403で登録成功、metadata非表示、警告を検証 | Clean |
| ユーザーが安全に失敗原因を判別可能 | 401/403/429/5xx/通信失敗を秘密情報なしの原因別422へ変換 | 原因別detailとprovider本文・キー非漏えいを検証 | Clean |
| 追加修正後の要件・仕様・運用コンソール文書との整合 | requirements/specificationをv1.10、tenant-auth-consoleをv1.2へ更新 | 実装・テスト・関連文書を相互照合 | Clean |

今回の変更範囲で新たな未記録不整合は検出しなかった。第5章の13件は既存監査で追跡中のため、今回スコープのClean判定には混在させない。

## 3. 整合を確認できた主な契約

| 契約 | 実装証拠 | テスト証拠 | 判定 |
|---|---|---|---|
| 明示選択した資料だけを生成・Q&Aに使用 | `GenerationSteps._kb_context` / `QAService._answer` | `test_v16_knowledge_instructions.py` | 整合 |
| 追加指示をアウトラインと台本へ分離して渡す | `GenerationSteps.generate_outline/generate_script` | `test_generation_keeps_instructions_separate...` | 整合 |
| Bearer tokenからテナントを決定し、他テナントIDを404にする | `auth.py` / tenant-scoped services | `test_multitenant_auth.py` | 基本経路は整合。網羅性はA-011参照 |
| BYOKの暗号化保存、マスク表示、削除後fail-closed | `crypto.py` / `IntegrationsService` | `test_crypto.py` / `test_e2e_core.py` | 整合 |
| BYOK登録検証失敗とオペレーター認証失効の分離 | `IntegrationsService` / Web API client | provider status/API/session回帰テスト | 整合 |
| SQLiteジョブと別Workerによる非同期再開 | `jobs.py` / `worker.py` | `test_e2e_async_durable.py` | 単一テナント経路は整合 |
| 明示公開前は視聴不可、編集・再生成で公開解除 | public routes / orchestrator | `test_public_viewer_api.py` | 整合 |
| Remotion動画に音声を配置し、probe済みMP4だけを公開可能にする | `Webinar.tsx` / `VideoRenderer` / `probe_media` | `test_audio_contract.py` / `test_public_viewer_api.py` | 整合 |
| Voice一覧取得と同意付与を分離し、明示証跡がないクローンVoiceを拒否 | `VoiceConsentService` / consent API | `test_voice_consent.py` / `voice-consent.test.ts` | 整合 |
| PDF/PPTXをブラウザ内で抽出し、本文だけ登録 | `fileExtraction.ts` / `WebinarListPage.tsx` | `fileExtraction.test.ts` / Playwright | 整合 |
| 根拠不足時の回答保留と引用の所属検査 | `QAService` / `gate_answer` | Q&A unit/API tests | 整合 |

## 4. 解消済みのCritical指摘

### A-001 — Resolved — Remotion動画にナレーション音声が合成されない

- 解消コミット: `1b63fec`（PR #10）。
- 実装: `timeline.audio_clips`をRemotionの`<Audio>`へフレーム位置付きで配置し、成果物ディレクトリの音声をレンダリング用public領域へ安全にステージする。音声長が動画全体より短い場合もcomposition終端まで無音でパディングする。
- 検証: `ffprobe`で映像・音声ストリーム、各ストリーム尺、全体尺を検査する。`test_audio_contract.py`が音声ステージング、配置、probe契約を回帰検証する。

### A-002 — Resolved — Remotion失敗時の構造ダブルが完成動画として扱われる

- 解消コミット: `1b63fec`（PR #10）。
- 実装: production rendererはRemotion不可・レンダリング失敗・probe失敗を例外として扱い、ウェビナーとジョブを`failed`にする。出力は一時ファイルへ生成し、probe合格後だけ原子的に確定する。
- 公開契約: `renderer=remotion`、`test_only=false`、`publishable=true`、probe成功、成果物実在のすべてを満たす動画だけを公開できる。doubleは明示的テストモード専用で常に公開不可。
- 検証: `test_durable_async_remotion.py`と`test_public_viewer_api.py`が失敗伝播と公開拒否を回帰検証する。

### A-005 — Resolved — 音声クローン同意を収集せず`consent_flag=true`にする

- 解消コミット: `1b63fec`（PR #10）。
- 実装: Voice一覧取得を読み取り専用にし、クローン/custom/未知カテゴリは`required`、既知のpremade Voiceだけを`not_required`とする。明示操作でテナント、Voice、証跡source、時刻、実行主体、規約文バージョンを記録するまで利用不可。
- 強制点: ウェビナー作成、ジョブ実行、TTS外部呼び出し直前で所属・有効性・同意をfail-closedに再検証する。同意取消とジョブ取消は独立操作とし、取消後の生成ステップは拒否する。
- キー差替え: 同一テナント・同一provider Voice IDなら同意対象は変わらないため証跡を維持し、active integrationだけを再関連付けする。キー削除時は関連Voiceを無効化する。
- 検証: `test_voice_consent.py`と`voice-consent.test.ts`が一覧取得、明示同意、取消、テナント境界、旧推定フラグのfail-closed移行、キー差替えを回帰検証する。

## 5. 未解消の不整合

### A-003 — High — 台本の事前承認ゲートがない

- 要件・仕様: BR-03、FR-005、設計原則`Human override`は、音声・動画生成前に台本を確認・修正・承認できることを要求する。
- 実装: Web UIは`auto_run=true`が既定で、作成後にOutlineからVideoまで連続実行する。台本編集は完成後に行い、再生成する方式。
- テスト: 台本編集テストも、いったん全工程を完了した後にpatchしてTTS以降を再実行する。
- 影響: 未確認の台本が外部TTSへ送信され、コスト消費と不適切な動画生成が発生しうる。
- 解消条件: Script完了時に`awaiting_approval`へ停止し、明示承認後にTTSへ進む。現行方式を採用するならBR-03/FR-005の合意変更が必要。

### A-004 — High — ElevenLabs Voice一覧とウェビナーのVoice選択が接続されていない

- 要件・仕様: BR-01/BR-04、FR-006bは、登録アカウントのVoice一覧から使用Voiceを選べることを要求する。
- 実装: 連携設定画面ではVoiceの同期・同意記録・取消ができ、APIは所属・有効性・同意を検証する。一方、ウェビナー作成画面にはVoice選択欄がなく、既定値`voice_id="default"`が送られる。
- テスト: API側のVoice検証は`test_voice_consent.py`で確認できるが、UIで同期済みVoiceを選んで作成する経路は存在せず、E2Eもない。
- 影響: 通常のUI操作ではクローンVoiceを指定できず、日英同一Voiceの受入条件を満たせない。
- 解消条件: 同意済みかつ利用可能なVoiceだけを作成フォームへ表示し、選択値を送信するUIとE2Eを追加する。

### A-006 — High — 本番Composeが転送元を無条件に信頼する

- 要件・仕様: 仕様書§11とREADMEは、公開Q&AのIP制限のため`--forwarded-allow-ips`を実際のプロキシIPだけに限定し、転送ヘッダーを無条件に信頼しないと定める。
- 実装: `docker-compose.prod.yml`はUvicornへ`--forwarded-allow-ips=*`を指定する。
- テスト: 転送ヘッダー偽装や本番プロキシ構成のテストはない。
- 影響: 到達経路によってはクライアントIPを偽装し、公開Q&Aのレート制限を回避できる。
- 解消条件: cloudflared/Caddyの実際の送信元CIDRだけを信頼し、構成テストで偽装ヘッダーを拒否する。

### A-007 — Medium — JSON Schema適合を強制していない

- 要件・仕様: AI-07は台本・Q&A・IntentのJSON Schema適合を要求する。
- 実装: LLMには`response_format={"type":"json_object"}`だけを指定し、返却dictをJSON SchemaまたはPydanticモデルで検証していない。主要キーがない場合はフォールバックするが、型・範囲・参照整合性は保証しない。
- テスト: 固定形状のモックレスポンスが中心で、壊れた構造への契約テストがない。
- 解消条件: 出力モデルとSchemaを定義し、検証失敗時の再試行/失敗処理をテストする。

### A-008 — Medium — TTS運用契約が部分実装

- 要件・仕様: FR-007と仕様書§5は、voice settingsを含むキャッシュキー、対象文だけのリテイク、障害時のedge-tts等への切替を記載する。
- 実装済み: TTSレスポンスの実形式を検出してMP3/WAVを正しい拡張子・MIME・durationで保存し、出力形式をキャッシュキーへ含める。壊れたキャッシュは再検査して再生成する。
- 未実装: 現在未使用のvoice settingsをキャッシュキーへ反映する契約、文単位リテイクの公開API/UI、代替TTSフラグ、429の指数バックオフ。
- テスト: MP3/WAV形式、duration、壊れた音声、キャッシュ再利用は検証するが、局所リテイクUI・代替経路は検証しない。
- 解消条件: 残す運用契約を絞って仕様化し、voice settings、再実行単位、再試行・代替方針を一致させる。

### A-009 — Medium — OrcaRouterガードレール有効化の証拠がない

- 要件・仕様: AI-09と仕様書§4はPII ShieldおよびPrompt Injectionガードを第一層として有効化する。
- 実装: アプリ側プロンプトにはKBを未信頼データとする指示がある一方、OrcaRouterリクエストや構成ファイルにガードレール有効化を示す設定がない。
- テスト: PII遮断・プロンプトインジェクション耐性のテストがない。
- 判定: 外部ダッシュボード設定の可能性はあるため「未実装」と断定せず、リポジトリからは**未検証**とする。
- 解消条件: 有効化方法と責任境界を記録し、代表的な攻撃入力の回帰テストまたは外部設定証跡を持つ。

### A-010 — Medium — 品質・尺・性能の受入条件をテストが証明しない

- 要件・仕様: BR-02、NFR-01〜05、KPI、仕様書§12は、5分動画、30分以内、Q&A p95、JA/EN、Golden Q&A 20件、groundednessを要求する。
- 実装・テスト: モック経路でJA/ENの完了は確認するが、動画尺、実音声、実プロバイダー遅延・コスト、20件のGolden Dataset、p95を測定しない。Playwrightは日本語1本の視覚再生だけ。
- 影響: 高カバレッジでも、審査上の品質・時間・コスト条件は未証明。
- 解消条件: 受入条件ごとの計測テストと保存可能な結果を追加する。

### A-011 — Medium — テナント受入条件のテストが一部不足

- 要件・仕様: FR-017と`tenant-auth-console.md`は、資料・ウェビナー・ジョブ・質問分析・BYOKに加え、非同期Workerが対象テナントのキーだけを使うことを要求する。
- 実装: `job.tenant_id`をWorkerへ引き継ぐ経路は存在する。
- テスト: 2テナントの資料・ウェビナー・ジョブ参照とBYOK一覧は確認するが、2テナントでWorkerを実行して各BYOKを使い分けるテスト、質問/回答/Intent/分析の相互分離テストはない。
- 解消条件: テナント別の異なるモックキーを用いた非同期生成と、質問分析の交差アクセスを追加する。

### A-012 — Medium — Retrieval実装が仕様上のembedding経路と一致しない

- 要件・仕様: 仕様書§4/§7はOrcaRouter経由embeddingを第一候補とし、vector similarityを使う。直接呼出し例外は構成フラグで管理する。
- 実装: 外部embeddingを使わず、64次元のhashing trickと語彙重複を組み合わせた決定論的スコアを使う。切替フラグやモデル記録はない。
- テスト: 小さな固定文のランキングだけで、意味検索品質を評価しない。
- 解消条件: MVPの正式方式を「ローカルhash/lexical」として要件合意するか、仕様どおりのembedding adapterと評価を実装する。

### A-013 — Medium — 旧PDF/URL擬似入力が正規APIとして成功扱いになる

- 要件・仕様: FR-001、OD-10/OD-11、仕様書§2.1は、PDF/PPTXをブラウザで抽出してサーバーへは`source_type=text`だけを送り、URL取り込みはMVPスコープ外とする。
- 実装: `SourceType.PDF/URL`も受理する。PDFは文字列上の簡易マーカー抽出、URLは`URL content placeholder for ...`への変換だけでchunk化し、いずれも`indexed`として返す。
- テスト: PDF/URL擬似入力を正常系として固定している。
- 影響: API利用者が実ファイルやURL本文を正しく取り込めたと誤認し、ブラウザ内抽出だけを許す境界とも一致しない。
- 解消条件: 正規APIでは`text`以外を422で拒否する。互換性が必要なら、実ファイル/URL取得ではないことを明示した別のテスト専用経路へ分離する。

### A-014 — Low — 質問分析ダッシュボードがない

- 要件・仕様: FR-015（Could）は質問一覧・Signal集計・エクスポートの簡易ダッシュボードを定義する。
- 実装: JSON/CSV APIはあるが、Web UIのルートと画面はウェビナー、詳細、連携設定だけ。
- 判定: Could要件のためMVP完了阻害ではないが、実装済みと読める概要記述とは不一致。
- 解消条件: UIを追加するか、現行MVPはAPIエクスポートのみと明記する。

### A-015 — Low — アプリのバージョン表示が一致しない

- 文書・パッケージ: README、`pyproject.toml`、`koebinar.__version__`は`0.3.0`。
- 実装: FastAPI/OpenAPIのversionは`0.1.0`、Web packageは`0.0.0`。
- 解消条件: 単一のバージョン源へ統一するか、各値の用途を明記する。

### A-016 — Low — テスト成功時にもDB接続未解放warningが多数出る

- 証拠: Python全291件は通過したが、SQLite `ResourceWarning`を中心に220 warnings。
- 影響: 現時点では失敗ではないが、テスト隔離の弱さ、ファイルロック、長時間実行時の資源枯渇を見逃しやすい。
- 解消条件: fixture/lifespanで`Store.close()`を保証し、warningを段階的にエラー化する。

## 6. 今回解消した文書上の不整合

1. `requirements.md`内でURL取り込みがIn Scope/概要とOut of Scopeの両方に存在したため、MVP対象をPDF/PPTX/Textへ統一した。
2. 要件定義書の改訂履歴を版順に並べ、現行メンテナンス版をv1.8とした。
3. 仕様書の「v1.1を実装粒度へ落とす」という古い参照をv1.8へ更新した。
4. Step 2を「機械的変換」とする記述を、実装どおり「OrcaRouterを使うがinstructionsは直接再送しない」へ修正した。
5. `web/README.md`のViteテンプレート文を、実際の起動・認証・テスト・制約へ置換した。
6. READMEの監査説明、Remotionのfail-closed公開契約、音声probeの検証境界を明記した。
7. Lightsail手順の古い「画面上部のAPIトークン」表現を、現在のログイン画面へ更新した。
8. PR #10で解消した音声合成、公開可否、Voice同意のCritical指摘を解消済みへ移し、残課題を現行実装に合わせた。
9. 登録時の外部プロバイダー認証エラーとKoebinarのオペレーター認証401を分離し、422契約と保存非更新を要件・仕様へ反映した。
10. OrcaRouter / ElevenLabsで実際に利用する検証・生成APIと、期限・IP・スコープ・上限等の案内内容を仕様へ反映した。
11. `tenant-auth-console.md`へ、検証失敗時のセッション維持、画面内エラー、`[i]`ヒントのアクセシビリティ契約を追加した。
12. ElevenLabsのUser Readを任意化し、TTS + Voices Readキーの登録、プラン情報取得不能警告、安全な原因別エラーを実装・仕様・テストで整合させた。

## 7. 推奨修正順

1. **P1**: A-003、A-004、A-006（承認フロー、Voice利用、公開構成の安全性）
2. **P2**: A-007〜A-013（生成契約、ガードレール、評価、テナント検証、Retrieval、URL API）
3. **P3**: A-014〜A-016（Could UI、メタデータ、テスト衛生）

未解消のCriticalは0件になったが、現時点で「設計・仕様・実装・テストに乖離なし」とは判定できない。自動テストの緑は、上記の未検査契約を達成した証拠にはならない。
