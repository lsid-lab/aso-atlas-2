# patent-collate（ASO Atlas 2 改造版）

USPTO特許のXML文書から、LLM（大規模言語モデル）を用いて核酸医薬品（ASO）などの実験データを抽出し、構造化するパイプラインです。

本プログラムは、[ASO Atlas 2](https://github.com/barneyhill/aso-atlas-2) の `patent_collate` を基に、**ScienceAidによる前処理の統合、LLMの切り替え、テーブル単位の独立実行、実験情報の記録、LLM生成スクリプトの保存**を追加したものです。元の研究で構築されたデータセットについては、[ASO Atlas 2（Hugging Face）](https://huggingface.co/datasets/barneyhill/aso-atlas-2) を参照してください。

## 1. 処理の概要

特許全文XMLからの一括実行（`run-all`）では、次の順番で処理します。

```text
特許全文XML
    ↓
ScienceAidによる前処理
    ├─ テーブルごとのXML
    ├─ テーブル周辺の文章（Context）
    └─ テーブル番号の対応表
    ↓
テーブルごとに独立して実行
    Step 1：XML → JSON（化合物ID・表中の実験データを抽出）
        ↓
    Step 2：HELM Annotation（配列・化学修飾情報をHELM形式へ変換）
        ↓
    Step 3：Schema Collation（指定スキーマに合わせて測定値を整理）
    ↓
テーブル別の抽出結果・生成Pythonスクリプト・実験記録を保存
```

### 改造版で追加した機能

- **特許全文XMLへの対応**：ScienceAidでテーブルXMLとContextを自動作成します。前処理済みテーブルXMLを直接使うモードも残しています。
- **テーブル独立実行**：各TableについてStep 1 → 2 → 3を実行し、入力・キャッシュ・結果を分けます。別テーブルの既出化合物IDがStep 2に影響する問題を避けるための構成です。
- **LLM切り替え**：OpenAI SDKによる既存経路に加え、LiteLLM経由でClaudeなどを選択できるようにしています。Claude Haiku 5.5での動作を確認済みです。Geminiなど未検証の組み合わせは事前に小規模テストを行ってください。
- **実験情報の記録**：モデル名、処理時間、API呼び出し数、トークン数、推定コストなどを保存します。
- **生成スクリプトの保存**：`run-all`ではLLMがツール呼び出しで生成したPythonスクリプトを、実行前にTable別・Step別に保存します。生成時のメタデータも残します。

## 2. 動作環境・インストール

- Python 3.11以上
- [`uv`](https://docs.astral.sh/uv/)（推奨）
- 使用するLLMプロバイダーのAPIキー

研究室のリポジトリから `Kashiwagi_aso_atlas2` ブランチを取得した後、`patent_collate` ディレクトリで依存ライブラリをインストールします。

```bash
git fetch origin
git switch --track origin/Kashiwagi_aso_atlas2
cd patent_collate
uv sync --frozen
```

## 3. APIキーの設定

利用するモデルに対応した環境変数を設定してください。以下の`YOUR_API_KEY`は各自のキーに置き換えます。

**OpenAI**

```bash
export OPENAI_API_KEY="YOUR_API_KEY"
```

**Anthropic Claude**

```bash
export ANTHROPIC_API_KEY="YOUR_API_KEY"
```

**Google Gemini（未検証）**

```bash
export GEMINI_API_KEY="YOUR_API_KEY"
```

APIキーはGitで管理するファイル、README、実験ログなどに書き込まないでください。APIの利用料金は契約先のプロバイダーに従います。

## 4. 入力データとスキーマ

### 特許全文XML（デフォルト）

`--input-dir`には、処理対象の特許全文XML（`.xml`）を置いたディレクトリを指定します。リポジトリの外でも構いません。

```text
/path/to/patent_xmls/
├── US20160251655A1.xml
└── （その他の特許全文XML）
```

**`--input-type`を省略した場合は`full-patent`**が適用され、ScienceAidによる前処理が自動実行されます。

すでにテーブル単位のXMLと対応する`_context.txt`がある場合は、`--input-type table`を使います。このモードではScienceAidの前処理を行いません。

### スキーマ（Step 3の出力項目）

ASOのin vitro阻害実験向けのサンプルを `examples/in_vitro_schema.json` に用意しています。

```json
{
  "compound_id": "string",
  "inhibition_pct": "Percent inhibition, float 0-100. Calculate as 100 - relative expression if needed.",
  "cell_line": "Cell line name, string.",
  "dosage_nm": "Dosage in nanomolar (nM), float."
}
```

スキーマは、出力するカラム名と、その意味をLLMへ伝えるためのJSONです。別の実験種別を抽出するときは、対象に合うスキーマを作成してください。スキーマのパスも任意に指定できます。

## 5. 実行方法

### 5.1 特許全文XMLから一括実行（必須オプションのみ）

`patent_collate`ディレクトリで実行します。以下は、`run-all`に必要なオプションだけを指定した最小構成です。

```bash
uv run python cli.py run-all \
  --input-dir /path/to/patent_xmls/ \
  --schema examples/in_vitro_schema.json \
  --output-dir results/experiment_01
```

- `--input-dir`：特許全文XMLがあるディレクトリを指定します。
- `--schema`：Step 3で使用する抽出スキーマを指定します。
- `--output-dir`：実験結果を保存する**新しい**ディレクトリを指定します（既存のディレクトリは不可）。

**処理時間やAPI料金の記録に追加オプションは不要です。** `run-all`では、モデル名、各Step・実験全体の処理時間、API呼び出し数、トークン数、推定コストなどを`experiment_summary.json`に自動保存します。Step 1〜3の抽出結果と、生成されたPythonスクリプトも従来どおりTable別に保存されます。モデルによっては料金情報がなく、推定コストを算出できない場合があります。

**この最小構成では、モデルはCLIの既定値、入力形式は`full-patent`、処理対象は全テーブル**になります。使用するLLMを変更する場合は`--model`、処理対象のテーブルを限定する場合は`--tables`を指定してください。`--model`などの共通オプションは`run-all`より**前**に、`--tables`などの`run-all`専用オプションは**後**に指定します。

`--tables`は特許に表示されるテーブル番号を指定します。XML内の出現順とは限らず、重複・曖昧さがある場合は`preprocessing/table_mapping.csv`で確認できます。省略すると全テーブルが対象になり、API利用量が増える場合があります。

### 5.2 ScienceAidの前処理だけ実行（LLMを呼ばない）

```bash
uv run --frozen python cli.py \
  run-all \
  --input-dir /path/to/patent_xmls/ \
  --output-dir results/preprocessing_01 \
  --tables 20 40 \
  --preprocess-only
```

`--preprocess-only`ではStep 1〜3を実行せず、スキーマも不要です。テーブル番号やContextの対応を確認するときに利用できます。

### 5.3 前処理済みTable XMLを入力する

```bash
uv run --frozen python cli.py \
  --model anthropic/claude-haiku-5-5 \
  --service-tier none \
  run-all \
  --input-type table \
  --input-dir /path/to/table_inputs/ \
  --schema examples/in_vitro_schema.json \
  --output-dir results/table_input_01
```

この場合、`--input-dir`に各テーブルのXMLと同名の`_context.txt`を置きます。`--input-type table`と`--tables`を同時に指定することはできません。

### 5.4 Stepごとの単独実行

元のStep 1〜3の単独実行コマンドも利用できます。Step 1には前処理済みのテーブルXMLとContextを渡してください。

```bash
uv run --frozen python cli.py step1 \
  --input-dir /path/to/table_inputs/ \
  --output step1.json

uv run --frozen python cli.py step2 \
  --table-data step1.json \
  --output step2.json

uv run --frozen python cli.py step3 \
  --table-data step1.json \
  --schema examples/in_vitro_schema.json \
  --output step3.json
```

※ 現時点で生成スクリプトのTable別・Step別保存先が自動設定されるのは`run-all`です。単独実行では同じディレクトリ構成でのスクリプト保存を前提にしないでください。

## 6. 出力ディレクトリの構成

### 6.1 出力ディレクトリの基本構成

`--output-dir results/experiment_01`を指定し、Table 20・40を処理した例です。

```text
results/experiment_01/
├── experiment_summary.json
├── preprocessing/
│   ├── atlas2_input/
│   └── table_mapping.csv
├── cache/
└── tables/
    ├── US20160251655A1_table_00020/
    │   ├── input/
    │   ├── step1_table_data.json
    │   ├── step2_helm_annotations.json
    │   ├── step3_collation_results.json
    │   └── generated_scripts/
    │       ├── step1/
    │       │   ├── <日時と一意ID>.py
    │       │   └── <日時と一意ID>.json
    │       ├── step2/
    │       └── step3/
    └── US20160251655A1_table_00040/
        ├── input/
        ├── step1_table_data.json
        ├── step2_helm_annotations.json
        ├── step3_collation_results.json
        └── generated_scripts/
            ├── step1/
            ├── step2/
            └── step3/
```

- `step1_table_data.json`：XMLから抽出した化合物・表データ
- `step2_helm_annotations.json`：HELM変換結果
- `step3_collation_results.json`：スキーマに基づく測定データ
- `generated_scripts/`：LLMが生成したPythonコード（`.py`）と生成履歴（`.json`）
- `experiment_summary.json`：モデル名、Step別・全体の処理時間、トークン数、API呼び出し数、推定コスト、実行状態など

生成スクリプトは実行前に保存され、再試行などで複数回生成された場合も別ファイルとして残ります。対応するメタデータJSONには、モデル名・Step・対象テーブル・ツール呼び出しID・生成日時・SHA-256ハッシュなどを記録します。**メタデータは生成履歴であり、スクリプト単位の実行成功・失敗を記録するものではありません。**

出力ディレクトリは既存のパスを上書きしないよう設計されています。実験ごとに新しい名前を指定してください。

### 6.2 検証データの保存先（研究室サーバー）

特許全文XMLを入力し、改造パイプラインで前処理からStep 1〜3まで実行した検証データを、研究室サーバーに保存しています。以下は代表的な実行例です。

- **サーバー**：`workstation01`
- **対象特許**：`US20160251655A1`
- **対象Table**：20、40
- **使用モデル**：Claude Haiku 5.5
- **入力形式**：特許全文XML（`full-patent`）

**サーバー上の基準ディレクトリ**

```text
/home/kkashiwagi/research/aso-atlas-2-litellm/patent_collate/
```

**検証データの構成**

```text
patent_collate/
│
├── reproduction/                              # 検証用の入力データ
│   └── US20160251655A1/                      # 対象特許の検証データ
│       └── source/                           # パイプラインへの入力フォルダ
│           └── US20160251655A1.xml           # 元の特許全文XML
│
└── results/                                   # パイプラインの実行結果
    └── claude_haiku55_script_save_run01/      # Claude Haiku 5.5による検証
        └── output/                           # 前処理・Step1〜3の出力
            │
            ├── preprocessing/                # 特許全文XMLの前処理結果
            │   ├── atlas2_input/             # 生成したTable XML・Context
            │   │   ├── US20160251655A1_table_00020.xml
            │   │   ├── US20160251655A1_table_00020_context.txt
            │   │   ├── US20160251655A1_table_00040.xml
            │   │   └── US20160251655A1_table_00040_context.txt
            │   └── table_mapping.csv         # 元のTable番号と生成ファイルの対応表
            │
            ├── tables/                       # Tableごとの独立実行結果
            │   ├── US20160251655A1_table_00020/
            │   │   ├── input/
            │   │   ├── step1_table_data.json
            │   │   ├── step2_helm_annotations.json
            │   │   ├── step3_collation_results.json
            │   │   └── generated_scripts/
            │   │       ├── step1/
            │   │       ├── step2/
            │   │       └── step3/
            │   │
            │   └── US20160251655A1_table_00040/
            │       ├── input/
            │       ├── step1_table_data.json
            │       ├── step2_helm_annotations.json
            │       ├── step3_collation_results.json
            │       └── generated_scripts/
            │           ├── step1/
            │           ├── step2/
            │           └── step3/
            │
            └── experiment_summary.json       # 使用モデル・処理時間・APIコスト等
```

- **元の特許全文XML**：`reproduction/US20160251655A1/source/US20160251655A1.xml`
- **Table XML・Context**：`results/claude_haiku55_script_save_run01/output/preprocessing/atlas2_input/`
- **Step 1〜3の出力**：`results/claude_haiku55_script_save_run01/output/tables/`

各Stepの出力ファイルや生成スクリプトの内容については、**6.1**を参照してください。`results/`には開発過程で実施したほかの検証結果も保存しています。

※ `experiment_summary.json`中の絶対パスは実行時のMac側のものです。研究室サーバー上の実際の保存場所は上記を参照してください。また、ほかのユーザーからの閲覧には、サーバー上のアクセス権限が必要です。

## 7. よく使うオプション（必須・任意）

以下の「必須」は`run-all`を通常実行する場合の指定を指します。`--preprocess-only`のときはスキーマを省略できます。

| オプション・指定 | 必須／任意 | 内容 |
|---|---|---|
| `run-all` | **必須** | ScienceAid前処理からStep 1〜3まで一括実行するサブコマンド。 |
| `--input-dir` | **必須** | 入力XMLを格納したディレクトリ。絶対パス・相対パスのいずれも指定可能。 |
| `--schema` | **原則必須** | Step 3の出力項目を定義したJSON。`--preprocess-only`の場合は不要。 |
| `--output-dir` | **必須** | 実験結果の保存先。まだ存在しないディレクトリを指定する。 |
| `--model` | 任意 | 使用するLLMのモデルID。省略時はCLIの既定モデル。Claude Haiku 5.5を使用する場合は`anthropic/claude-haiku-5-5`を指定する。 |
| `--input-type` | 任意 | `full-patent`（既定値：特許全文XMLから前処理）か`table`（既存のTable XML・Contextを使用）を選択する。 |
| `--tables` | 任意 | 表示テーブル番号を空白区切りで指定（例：`--tables 20 40`）。省略時は全テーブル。`full-patent`のみ使用可能。 |
| `--preprocess-only` | 任意 | ScienceAid前処理のみを実行し、LLMによるStep 1〜3は実行しない。 |
| `--service-tier` | 任意 | APIのサービス階層（`flex`・`default`・`none`）。Claudeの実行例では`none`を指定している。 |
| `--max-workers` | 任意 | 並列処理するワーカー数。例：`--max-workers 1`。 |
| `--max-attempts` | 任意 | LLM処理の最大試行回数。例：`--max-attempts 3`。 |
| `--reasoning-effort` | 任意 | 対応モデルの推論設定（`low`・`medium`・`high`）。 |
| `--api-key` | 任意 | OpenAI経路でAPIキーを直接渡す指定。通常は各プロバイダーの環境変数を利用する。 |
| `--debug` | 任意 | 詳細なデバッグログを有効にする。 |
| `--cache-dir` | 任意 | キャッシュディレクトリを変更する。 |
| `--frozen` | 任意（`uv`のオプション） | `uv.lock`を更新せず既存のロック情報で実行する。研究の再現性のため推奨。 |

**使い分けのポイント**

- **モデルを切り替える**：`--model`を指定します。ClaudeなどのAPIキーは実行前に環境変数へ設定してください。
- **特定の表だけ処理する**：`--tables 20 40`などを指定します。省略すると対象の全テーブルを処理します。
- **以前の実験と条件をそろえる**：`--model`・`--service-tier`・`--max-workers`・`--max-attempts`を明示します。これらを省略しても時間・トークン数・推定コストの**記録機能自体は変わりません**が、処理条件は既定値になります。
- **入力テーブルが前処理済み**：`--input-type table`を指定します。この場合`--tables`は指定できません。

共通オプション（`--model`、`--max-workers`など）はサブコマンド`run-all`より前に、`run-all`専用オプション（`--input-dir`、`--tables`など）は後に指定します。

利用できる引数は次のコマンドで確認できます。

```bash
uv run --frozen python cli.py --help
uv run --frozen python cli.py run-all --help
```
