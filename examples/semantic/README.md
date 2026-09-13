# 可检验的语义结果样例

这些是维护与宿主接入样例，不由 runner 自动复制到任务，不是新的必填过程文档。
JSON 用实际四类 schema 和 audience 子结构验证；它们**不是可直接冒充真实作业的回执**。

## 文件分工

- plan：确认前的课次语义计划；空 sources 仅用于自包含例子，不表示教材已读取。
- author-result / revision-result：结果字段示范。真实作业还须回应其全部 feedback/repair IDs，不能照抄这里的示例 ID。
- review-result / diagnosis-result：基于 review-fixture 的具体问题，诊断区分 observed/possible。
- attention-input、audience 两种结果：完整的当前段与候选引用示例；不是 provider request/receipt。
- review-fixture/presentation.md：合法 Markdown，第一页**故意留有备课目标句**供审核测试，不是可投产的优良课件模板。
- calibration-cases：取自用户反复指出的错误类型及保护性反例，用于人工/实际模型校准，不把静态断言伪装成模型教学能力验证。

## 核对方式

测试验证 schema、真实 slide ID/quote、attention候选与finding对应，以及受限源码语法。
校准案例另用于评估实际模型是否采用正确判断标准；本发行没有声称它已运行真实模型实验。
