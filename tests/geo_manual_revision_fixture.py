"""LOCAL manual revision based on the private customer's topic and bound facts.

Explicit test editing, never a production rewrite/approval tool. The customer's
full body is not embedded here. Unknown claims are removed; bounded information
instructions and strict fact quotes remain. No customer has approved this edit.
"""
FACT4_TRANSLATION = "诺德 NORD DRIVESYSTEMS 的 MAXXDRIVE 工业齿轮箱为苛刻环境下的连续运行而设计。"


def revised_body(collections):
    source = next(row for row in collections["geo_channel_variants"] if row["id"] == 2)
    facts = {row["id"]: row for row in collections["geo_facts"]}
    # Data fields originate in the original draft's information checklist.
    # Complete bounded actions replace ambiguous causal/property commentary.
    groups = [
        [("建议先整理", "设备用途、输出扭矩、转速、启动条件与计划运行时间"),
         ("请核对", "负载变化、环境温度、通风条件与运行方式"),
         ("请向厂家提交", "工况清单和待确认事项"),
         ("请保留", "书面回复、方案版本、确认日期与未决问题")],
        [("请准备", "设备用途、机械负载、启动条件、冲击条件、运行时间和运行方式"),
         ("请整理", "环境条件、安装方向、可用空间、连接位置与检修安排"),
         ("请向选型团队提交", "工况资料、现场资料、设备资料和待确认事项"),
         ("请注明", "资料来源、确认日期、引用来源、具体型号和具体配置")],
        [("请核对", "输入资料、设备需求、机械负载、安装空间与维护资料"),
         ("请检查", "方案回复、书面回复、方案版本、具体型号、配置和适用前提"),
         ("请记录", "资料来源、来源链接、系列名称、未决问题与待确认事项"),
         ("请保存", "确认日期、确认记录、工况清单、设备资料和方案版本")],
        [("请准备", "环境温度、通风条件、运行时间、运行方式和散热配置"),
         ("请补齐", "安装方向、安装空间、连接位置、检修条件和维护资料"),
         ("请向技术团队提交", "现场资料、工况资料、设备用途和待确认事项"),
         ("请保留", "书面回复、具体型号、具体配置、适用前提和确认记录")],
        [("请整理", "工况表、计划运行方式、计划运行时间和负载变化"),
         ("请确认", "输入资料、方案版本、具体型号、具体配置和确认日期"),
         ("请注明", "资料来源、来源链接、系列名称、引用来源和未决问题"),
         ("请保存", "设备资料、现场资料、方案回复、确认记录和待确认事项")],
        [("建议先整理", "工况清单、输出扭矩、转速、环境条件和安装方向"),
         ("请向厂家提交", "设备需求、现场资料、具体型号与待确认事项"),
         ("请核对", "书面回复、方案版本、具体配置、适用前提和未决问题"),
         ("请保留", "资料来源、系列名称、确认日期、确认记录与来源链接")],
    ]
    prose = ["".join(action + fields + "。" for action, fields in group) for group in groups]
    prose[3] = "".join(f"步骤 {index}：" + action + fields + "。" for index,(action,fields) in enumerate(groups[3],1))
    quote = lambda n: facts[n]["statement"].rstrip(".") + "."
    return "\n\n".join([
        "# " + source["title"], FACT4_TRANSLATION + "\n" + prose[0],
        "## 定义与选型参数", quote(4) + "\n" + quote(5), prose[1],
        "| 资料 | 操作 |\n| --- | --- |\n| 工况清单 | 请核对输入资料 |\n| 方案回复 | 请保留确认记录 |",
        prose[2], "## 操作步骤", prose[3], quote(6) + "\n" + prose[4],
        "## 结论与常见问题", FACT4_TRANSLATION + "\n" + prose[5],
        "**Q：如何核对具体配置？**\n请确认具体型号、具体配置和适用前提。",
        "**Q：怎样准备现场资料？**\n请补充设备用途、安装方向和检修安排。",
        "## 来源", "\n".join(row["source_url"] for row in facts.values()),
    ])
