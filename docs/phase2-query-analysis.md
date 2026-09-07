# Phase 2 Chinese Query Failure Analysis

## Outcome

The expanded benchmark contains 25 queries. Ten relevant queries retrieve an expected document,
two access-sensitive queries correctly return no result, and thirteen relevant queries miss.
There are no cross-source leaks. Every miss occurs before ranking because the candidate does not
reach the current 35% distinct-term coverage threshold.

## What already works

- Exact domain terms: `WAL`, `RUNNING`, `BOM`, `BM25`, change-event names.
- Queries sharing several Chinese bigrams with the source text.
- Multi-document retrieval when both documents contain the explicit query vocabulary.
- Source filtering: payroll and private-chat documents never enter allowed-source results.

## Phase 2 lexical improvements

These cases retain useful literal evidence and should be improved without embeddings:

| Query pattern | Example | Root cause | Appropriate fix |
| --- | --- | --- | --- |
| Technical spelling | `UTF16 大端小端` | `UTF16` and `UTF-16` tokenize differently | Normalize punctuation inside technical identifiers |
| Mixed Chinese/English | `junction 和软链接` | Exact English hit is diluted by conversational tokens | Score coverage using informative terms |
| Long question form | `如何阻止路径跳出授权文件夹` | Question words inflate the coverage denominator | Remove a small, documented Chinese stopword set |
| Explicit operation | `重命名一个文件会被识别成什么` | Relevant bigrams exist but coverage is below the hard cutoff | Use weighted coverage instead of raw distinct-token ratio |
| Metric wording | `衡量检索排序质量看哪些指标` | `检索`、`排序`、`指标` match but filler dominates | Title boost plus informative-term coverage |
| Source tracing | `搜索结果如何追溯回原文件` | Evidence is split across two relevant documents | Aggregate document evidence across chunks/results |

The coverage threshold should remain fail-closed, but it should measure rare or technical terms
more heavily than single common Han characters. Lowering it globally would restore noisy matches
such as a document matching only the character `词`.

## Phase 3 semantic targets

These queries express the right intent with substantially different vocabulary. A larger synonym
table would overfit the benchmark; they are better acceptance cases for embeddings or a local
query-expansion model.

| Query | Source wording | Missing relation |
| --- | --- | --- |
| `怎么证明源文件没有被碰过` | 比较哈希、大小、名称和修改时间 | “没碰过” means integrity preservation |
| `上次运行突然断电后怎么恢复` | 崩溃、遗留 RUNNING、从成功游标重试 | “断电” implies interrupted process |
| `长尾查询速度用什么统计量` | P50/P95 查询延迟 | percentile metrics represent tail latency |
| `系统是否偷偷联网调用云模型` | 不得静默上传或回退云端模型 | colloquial “偷偷联网” means silent remote use |
| `统一文档对象保存哪些字段` | SourceDocument 包含稳定 ID 等 | “统一文档对象” refers to the canonical model |
| `网页服务是不是暴露给局域网` | 只绑定 127.0.0.1 | loopback binding prevents LAN exposure |

## Decision

Phase 2 should next implement technical-token normalization, a small language-independent question
word filter, and IDF-weighted candidate coverage. The expanded benchmark remains unchanged while
the implementation changes. Phase 3 must then demonstrate improvement on the semantic-target rows
without raising the forbidden-result rate above zero.

## Reproduction

## Implemented lexical improvement

The phase 2 changes were applied with the benchmark frozen:

- normalize punctuation inside technical identifiers, such as `UTF-16` → `utf16`;
- remove a small documented set of question-form noise phrases;
- exclude single Han characters from candidate gating when longer terms exist;
- use IDF-weighted informative-term coverage with a conservative threshold;
- index title terms with additional weight.

Recall@5 and Recall@10 improved from 0.46 to 0.66 and MRR improved from 0.38 to 0.56. The
forbidden-result rate stayed at zero. Remaining misses predominantly require semantic relations or
cross-document evidence and therefore remain unchanged for phase 3.

## Reproduction

Run the detailed diagnostic from the repository root:

```powershell
$env:PYTHONPATH = "src"
python scripts/diagnose_retrieval.py
```

The command uses only fictional fixtures and a temporary database.
