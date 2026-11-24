# 江湾堤线测绘交班

江湾堤线养护站用这套工具把早班测量交给离线巡检员。资料员冻结测量及质量记录并发行站件。巡检员选用实收件复核一条固定测线上的视线。值班员按正式报告中的确证位置安排现场核查，按缺口安排补测，再按原报告号对照前后结论。

## 运行

在项目根目录使用 Python 3.11 或更高版本。工程仅用标准库。

```sh
python3 -B check_project.py
python3 -B demo.py
```

控制台物化项目时提供 `check_project.py`。它先跑完整回归，再依次执行 `surface_examples.py`（V1/V2 样例）和 `check_highest.py`（发件披露、断源复核、拒收、签存失败重试与重开领取），任一失败以非零退出。在独立源码目录也可直接执行完整回归。

```sh
python3 -B -m unittest discover -s tests -t .
```

演示从 `samples/shift.json` 读取线档、测簿、测段和视线，在临时目录内分别保存站内库与离线库。先发行 A 和 B 并关闭站内库，在 `[0,6]` 内用高程 1 米的水平视线复核。A 覆盖 `[0,1)` 且高程为 0，B 覆盖 `[4,6]` 且高程为 2。预期在 4 米确证遮挡，出处为 B，缺口 `[1,4)` 使首个遮挡待确认。C 补测 `[1,4)` 且恒高 0，重新指定 A、B、C 后，同一确证位置成为已确认的首个遮挡。演示重开离线库并核对两份报告和各自的原回执。

同一演示随后发行 V2 最高实测面：A 在 `[0,1)`、B 在 `[4,6]`，各自一段即是当地最高面，低位与缺测证据不随件。外协沿原入口实收后，以同一闭窗和视线复核，签出 4 米、出处 B、缺口 `[1,4)`，并重开离线库按原报告号领取同一报告与回执（`POINTWISE_HIGHEST`）。

## 工作流程与数据

1. 开站时初始化线档、修订、发行库存、离线目录和报告表。样例线档仅补缺失编号。已保存的线名及既有业务记录在重开和重复初始化后保留。
2. 测量员交回实际测簿和具名原段。每段里程严格递增，原段之间可相接或重叠。每个原段的出处须引用本次测簿里的实际条目。
3. 登记固定修订，同时固定质量裁决。段标记为 `fail` 或仪器核查失败时显式记作缺测。补测和勘误登记为独立后继修订，保留前修订及其出处。
4. 资料员以发行请求号和固定修订号发行 V1 站件。站件携带逐段有理量值、端点资格及出处引用，或携带带原因的缺测范围。测簿原文留站。以同一请求号及修订号补发时取回原字节。
5. 巡检员断开站内库后投递站件。离线目录验证外层版本、摘要、正文结构和身份绑定，再登记首件。同一规范正文重投返回原件号。
6. 巡检员指定线号、实收件集合、闭里程窗和两端视线高程。程序从指定证据求确证遮挡并核查覆盖。选件顺序及重复项对同一固定请求没有影响。
7. 离线签存固定请求、结果、证据和成功回执。补测件实收后可重新选件发起新请求。已经签存的报告保留其原选件和质量裁决。
8. 值班员在跨班重开后按号领取原报告及原回执，分别使用确证位置和待补测范围。领取只读取离线档案。

## 计算口径

里程与高程使用米。输入支持整数、`Fraction`、十进制文本和分数字符串，输出使用约分后的有理文本。浮点值、布尔值、零分母和逆序范围会被拒绝。线号固定里程和高程参照。原段覆盖左闭右开，只有原测标记 `terminal` 时才实测其右端。右端高程可用作本段线性关系的极限值。闭查询窗裁剪后的端点仍遵守原段归属。单点窗要求两端视线高程一致。

地面高程与视线分别在各自定义范围内线性计算。地面等于或高于视线即构成遮挡。重叠处任一合格段均可确证。报告保存最早确证位置，并按站件号、修订号、原段号和出处汇集同点支持证据。缺测不提供高程，其他所选件的合格段可提供当地覆盖。

有确证时，覆盖范围取窗首至确证位置之前。`blocked_confirmed` 表示此前全覆盖，`blocked_pending` 表示已有确证位置且此前还有待补测缺口。无确证时，`clear` 表示整个闭窗通视，`needs_survey` 表示全窗内有未知范围。缺口保留开闭边界，也可为单点。已明确线号的空选件视作无测量证据。

## Python 接口

站内调用共用一个 SQLite 连接，离线目录和报告使用独立的离线连接。初始化和写入口使用调用方空闲连接，成功返回前提交，失败回滚。显示名称可按原线号和原基准重登记。线号对应的参照保持固定。

| 操作 | 调用与结果 |
| --- | --- |
| 初始化站内 | `LineStore(db).initialize(default_lines)`、`RevisionStore(db, lines).initialize()`、`IssueRegistry(db).initialize()` |
| 登记线档 | `lines.register(SurveyLine(line_id, name, datum))` |
| 冻结原测 | `revisions.record(line_id, book, rows)` 返回修订号。`book` 含 `id` 和条目号到原文的 `entries`，`rows` 的格式见样例 |
| 更正原测 | `revisions.correct(revision_id, book, rows)` 返回同线后继修订号。传入的原测形成后继自身的完整提交，旧修订仍可读取 |
| 发行与补发 | `release(revisions, registry, revision_id, request_id)` 返回 `IssueEntry`，其中 `bundle_id` 是 `B:` 加请求号，`payload` 是站件字节。`registry.get(bundle_id)` 按发行号查原件 |
| 发行最高面 | `release_highest(revisions, registry, revision_id, request_id)` 以同号发行 V2 最高实测面，返回 `IssueEntry`。同号同修订同版本重投取回原字节；同号改修订或改版本报 `ValueError` |
| 初始化离线 | `AcceptedCatalog(db).initialize()` 和 `PublicationStore(db).initialize()` |
| 实收站件 | `receive(catalog, payload)` 返回实收件号。`catalog.get(bundle_id)` 返回首投存档字节及已验正文，可区分 V1/V2 |
| 核定与签存 | `assess(catalog, archive, request_id=..., line_id=..., bundle_ids=..., start=..., end=..., left_height=..., right_height=...)` 返回 `Assessment`，含 `report` 和 `receipt` |
| 核定最高面 | `assess_highest(...)` 输入与结果同 `assess`，只消费 V2 实收件，签出最高实测面达到或超过视线的最早实测点及其并列最高出处 |
| 领取历史 | `fetch(offline_db, report_id)` 返回 `(ReportSnapshot, Receipt)`。`encode_snapshot(report)` 可得到包含有理文本的 JSON 快照 |

模块分别位于 `survey`、`issue`、`intake`、`review` 和 `reports`。`demo.py` 展示了导入和连接生命周期。站件 JSON 外层含 `version`、`bundle_id`、`line_id`、`revision_id`、`body` 和 `digest`。正文重复绑定三个身份字段并携带 `segments` 与 `missing`。摘要是正文按键排序、用紧凑 ASCII JSON 编码后的 SHA-256。实收重投比较规范正文及身份，保留首件字节。跨发行者共用目录时，发行者应使用独立的请求号命名范围。

V2 沿用同一外层字段，`version` 为整数 2，正文为三个身份字段与 `surface`。`surface` 含 `spans` 与 `points`：每段有起止里程、`left_closed`/`right_closed`、两端精确有理高程和达到当地最高实测值的原段 `supports`；每个点有单一 `chainage`、`height` 与并列支持。支持记录含 `segment_id` 和测簿出处 `source`；低位证据、缺测原段与测簿正文留站。两份形状可由实际字节核对实测域、精确高程和全部并列出处，范围开闭与单点资格可区分。

无效坐标、虚构出处、错件、非法请求、同号异件或同请求号异参会抛出 `ValueError`。未知测线、修订或报告的直接查找抛出 `KeyError`，选件缺失按复核输入错误处理。报告按 `RPT:` 加请求号归档，回执绑定该报告号和请求号。复投相同规范请求可复领原报告与回执。数据库写入错误保留 SQLite 异常，出现写入或提交失败时本次报告与成功回执均不可见。

## 原回归

| 冻结场景 | 回归 |
| --- | --- |
| v1、v2 | `tests.test_issue.IssueTests` 核对补发、初始化、更正、发行回滚、逆序和出处拒绝 |
| v3、v4、v7 | `tests.test_review.ReviewTests` 核对手算交点、重叠、闭窗边界、缺口状态、错件和非法窗 |
| v5 | `tests.test_handover.HandoverTests` 核对分段内容、真坡交点、补测资格、质量勘误及重开原领取 |
| v6 | `tests.test_intake.IntakeTests` 核对合法重投、同号有效冲突、坏摘要及内外绑定 |
| v8 | `tests.test_reports.ReportTests` 使用真正的 SQLite 写入失败及延迟约束提交失败核对回滚与续办 |
| 测绘入口 | `tests.test_survey.SurveyTests` 核对米值、固定参照、原测留站与质量口径 |
| 最高面 | `tests.test_surface.HighestSurfaceTests` 核对 V2 发件只带最高面、并列与单点保全、同号版本冲突、坏件/混版/错线拒收，以及签存失败重试与重开原号领取 |
