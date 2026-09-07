"""Import the curated format dataset into Casework without trusting product output as GT."""
from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path

from .common import DEFAULT_HOME, atomic, digest, now, read, sha
from .maintenance import apply_project, modules

PROJECT_ID = "deckprobe-format-dataset"

SOURCE_POLICY = {
    "Apache_Tika": ("Apache-2.0", True),
    "Apache_POI": ("Apache-2.0", True),
    "HuggingFace_OmegaUse_OfficeVal": ("Apache-2.0", True),
    "HuggingFace_Zenodo10K": ("CC-BY-4.0", True),
    "HuggingFace_SpreadsheetBench": ("CC-BY-SA-4.0", True),
    "HuggingFace_OfficeComprehensionBenchmark": ("CDLA-Permissive-2.0", True),
    "cupertino_files": ("MIT project; fixture redistribution requires per-file attribution review", False),
    # These sources remain available for local review but are not exported to public CI.
    "delivr_to_file_samples": ("CC-BY-NC-4.0", False),
    "OmniDocBench": ("research-only / redistribution not established", False),
}


def _purpose(filename, declared_support):
    text = filename.lower()
    if "omnidocbench" in text:
        return {"summary": "扫描纯图 PDF 与零值边界（Missing vs Zero）",
                "checks": [{"label": "页面数量", "type": "fact", "target": "pdf.page_count"},
                           {"label": "无交互表单字段", "type": "fact", "target": "pdf.form_field_count", "note": "纯扫描件无表单字段，必须为0而非空或报错"},
                           {"label": "无注释对象", "type": "fact", "target": "pdf.annotation_count", "note": "纯扫描件无注释，必须为0"}],
                "source": "dataset-manifest-v1"}
    legacy_purposes = {
        "word旧版宏文档.doc": {
            "summary": "Word 97-2003 宏/VBA能力与作者元数据",
            "checks": [{"label": "宏/VBA 存在性与数量", "type": "fact", "target": "security.has_vba"},
                       {"label": "作者元数据", "type": "fact", "target": "document.author"}]
        },
        "excel旧版宏工作簿.xls": {
            "summary": "Excel 97-2003 宏/VBA能力与多工作表名称",
            "checks": [{"label": "宏/VBA 存在性与数量", "type": "fact", "target": "security.has_vba"},
                       {"label": "工作表数量", "type": "fact", "target": "excel.sheet_count"},
                       {"label": "工作表名称列表", "type": "fact", "target": "excel.sheet_names"}]
        },
        "powerpoint旧版宏演示文稿.ppt": {
            "summary": "PowerPoint 97-2003 宏/VBA能力与幻灯片统计",
            "checks": [{"label": "宏/VBA 存在性与数量", "type": "fact", "target": "security.has_vba"},
                       {"label": "幻灯片数量", "type": "fact", "target": "powerpoint.slide_count"}]
        },
        "word旧版嵌入pdf文档.doc": {
            "summary": "Word 97-2003 嵌入 PDF 结构与标题作者元数据",
            "checks": [{"label": "嵌入对象的存在、数量和类型", "type": "fact", "target": "security.has_embedded_ole"},
                       {"label": "标题元数据", "type": "fact", "target": "document.title"},
                       {"label": "作者元数据", "type": "fact", "target": "document.author"}]
        },
        "word旧版模板.dot": {
            "summary": "Word 97-2003 模板类型识别与段落页数统计",
            "checks": [{"label": "模板格式与类型识别", "type": "fact", "target": "word.is_template"},
                       {"label": "页面数量", "type": "fact", "target": "word.page_count"},
                       {"label": "标题元数据", "type": "fact", "target": "document.title"}]
        },
        "excel旧版普通工作簿.xls": {
            "summary": "Excel 97-2003 多工作表结构与有序名称列表",
            "checks": [{"label": "工作表数量", "type": "fact", "target": "excel.sheet_count"},
                       {"label": "工作表名称列表", "type": "fact", "target": "excel.sheet_names"},
                       {"label": "标题元数据", "type": "fact", "target": "document.title"}]
        },
        "excel旧版模板.xlt": {
            "summary": "Excel 97-2003 模板类型识别与工作表名称",
            "checks": [{"label": "模板格式与类型识别", "type": "fact", "target": "excel.is_template"},
                       {"label": "工作表数量", "type": "fact", "target": "excel.sheet_count"},
                       {"label": "工作表名称列表", "type": "fact", "target": "excel.sheet_names"}]
        },
        "powerpoint旧版综合元素.ppt": {
            "summary": "PowerPoint 97-2003 综合元素与标题作者元数据",
            "checks": [{"label": "幻灯片数量", "type": "fact", "target": "powerpoint.slide_count"},
                       {"label": "标题元数据", "type": "fact", "target": "document.title"},
                       {"label": "作者元数据", "type": "fact", "target": "document.author"}]
        },
        "powerpoint旧版放映文件.pps": {
            "summary": "PowerPoint 97-2003 放映类型识别与幻灯片统计",
            "checks": [{"label": "放映文件格式与类型识别", "type": "fact", "target": "powerpoint.presentation_kind"},
                       {"label": "幻灯片数量", "type": "fact", "target": "powerpoint.slide_count"},
                       {"label": "标题元数据", "type": "fact", "target": "document.title"}]
        },
        "powerpoint旧版模板.pot": {
            "summary": "PowerPoint 97-2003 模板类型识别与幻灯片统计",
            "checks": [{"label": "模板格式与类型识别", "type": "fact", "target": "powerpoint.presentation_kind"},
                       {"label": "幻灯片数量", "type": "fact", "target": "powerpoint.slide_count"},
                       {"label": "标题元数据", "type": "fact", "target": "document.title"}]
        },
        "pdf表单与注释样本.pdf": {
            "summary": "PDF 交互结构、页面与XMP元数据全集（Hero Document）",
            "checks": [{"label": "页面数量", "type": "fact", "target": "pdf.page_count"},
                       {"label": "PDF 表单字段数量", "type": "fact", "target": "pdf.form_field_count"},
                       {"label": "批注、注释或评论数量", "type": "fact", "target": "pdf.annotation_count"},
                       {"label": "XMP元数据存在性", "type": "fact", "target": "pdf.has_xmp"},
                       {"label": "线性化流式结构", "type": "fact", "target": "pdf.linearized"},
                       {"label": "MIME媒体类型", "type": "fact", "target": "document.mime_type"}]
        },
        "word_家居零售价目册_66页308表115图.docx": {
            "summary": "Word 现代页面、段落、词数、表格与图片资产全集（Hero Document）",
            "checks": [{"label": "页面数量", "type": "fact", "target": "word.page_count"},
                       {"label": "段落数量", "type": "fact", "target": "word.paragraph_count"},
                       {"label": "单词统计", "type": "fact", "target": "word.word_count"},
                       {"label": "字符统计", "type": "fact", "target": "word.character_count"},
                       {"label": "原生表格对象数量", "type": "fact", "target": "word.table_count"},
                       {"label": "图片资源与图像对象数量", "type": "fact", "target": "word.unique_image_asset_count"},
                       {"label": "MIME媒体类型", "type": "fact", "target": "document.mime_type"}]
        },
        "excel_多子表汇总_61工作表178表格.xlsx": {
            "summary": "Excel 多工作表、有序名称与表格结构全集（Hero Document）",
            "checks": [{"label": "工作表数量", "type": "fact", "target": "excel.sheet_count"},
                       {"label": "工作表名称列表", "type": "fact", "target": "excel.sheet_names"},
                       {"label": "原生表格对象数量", "type": "fact", "target": "excel.table_count"},
                       {"label": "MIME媒体类型", "type": "fact", "target": "document.mime_type"}]
        },
        "ppt_zenodo_用户画像工具包_49页80图.pptx": {
            "summary": "PowerPoint 多页幻灯片、图片资产与16:9宽屏画布全集（Hero Document）",
            "checks": [{"label": "幻灯片数量", "type": "fact", "target": "powerpoint.slide_count"},
                       {"label": "图片资源与图像对象数量", "type": "fact", "target": "powerpoint.unique_image_asset_count"},
                       {"label": "16:9画布比例与物理尺寸", "type": "fact", "target": "powerpoint.aspect_ratio"},
                       {"label": "MIME媒体类型", "type": "fact", "target": "document.mime_type"}]
        },
        "keynote表格与图片演示文稿.key": {
            "summary": "Keynote 幻灯片、表格、图片与1080p画布全集（Hero Document）",
            "checks": [{"label": "幻灯片数量", "type": "fact", "target": "keynote.slide_count"},
                       {"label": "原生表格对象数量", "type": "fact", "target": "keynote.table_count"},
                       {"label": "图片资源与图像对象数量", "type": "fact", "target": "keynote.unique_image_asset_count"},
                       {"label": "1080p宽屏画布尺寸", "type": "fact", "target": "keynote.slide_size"},
                       {"label": "MIME媒体类型", "type": "fact", "target": "document.mime_type"}]
        },
        "numbers多工作表结构工作簿.numbers": {
            "summary": "Numbers 多工作表、有序名称与表格结构全集（Hero Document）",
            "checks": [{"label": "工作表数量", "type": "fact", "target": "numbers.sheet_count"},
                       {"label": "工作表名称列表", "type": "fact", "target": "numbers.sheet_names"},
                       {"label": "原生表格对象数量", "type": "fact", "target": "numbers.table_count"},
                       {"label": "MIME媒体类型", "type": "fact", "target": "document.mime_type"}]
        },
        "pages多章节页眉页脚文档.pages": {
            "summary": "Pages 多章节、缓存页数、正文长度与换行全集（Hero Document）",
            "checks": [{"label": "文档章节结构数量", "type": "fact", "target": "pages.section_count"},
                       {"label": "章节名称列表", "type": "fact", "target": "pages.section_names"},
                       {"label": "缓存页数", "type": "fact", "target": "pages.cached_page_count"},
                       {"label": "正文长度", "type": "fact", "target": "pages.body_text_length"},
                       {"label": "正文段落换行数", "type": "fact", "target": "pages.body_paragraph_break_count"},
                       {"label": "页面物理尺寸", "type": "fact", "target": "pages.page_size"},
                       {"label": "页面方向", "type": "fact", "target": "pages.orientation"},
                       {"label": "MIME媒体类型", "type": "fact", "target": "document.mime_type"}]
        },
        "word_公共书房运营规划书_55页18图表部件.docx": {
            "summary": "Word 复杂长文档表格、页面与图表部件",
            "checks": [{"label": "原生表格对象数量", "type": "fact", "target": "word.table_count"},
                       {"label": "页面数量", "type": "fact", "target": "word.page_count"},
                       {"label": "图表部件数量", "type": "fact", "target": "word.chart_part_count"}]
        },
        "word_职称评审表_22页多页眉页脚.docx": {
            "summary": "Word 复杂表格、页面与多节页眉页脚",
            "checks": [{"label": "页面数量", "type": "fact", "target": "word.page_count"},
                       {"label": "页眉与页脚部件数量", "type": "fact", "target": "header_footer_count"}]
        }
    }
    if text in legacy_purposes:
        return {**legacy_purposes[text], "source": "dataset-manifest-v1"}
    checks = []
    patterns = [
        (("设计技术",), "4:3 画布比例与尺寸", "aspect_ratio"),
        (("表单",), "PDF 表单字段数量", "pdf.form_field_count"),
        (("加密", "密码"), "加密与受保护行为", "security.encrypted"),
        (("签名",), "数字签名存在性与数量", "security.has_signatures"),
        (("宏",), "宏/VBA 存在性与数量", "security.has_vba"),
        (("外链", "超链接"), "外部关系的存在、数量和目标", "security.has_external_relationships"),
        (("javascript", "js"), "JavaScript 动作存在性", "security.has_javascript"),
        (("附件",), "嵌入附件的存在、数量和类型", "pdf.attachment_count"),
        (("嵌入对象", "嵌入pdf"), "嵌入对象的存在、数量和类型", "security.has_embedded_ole"),
        (("公式",), "公式对象或公式单元格数量", "formula_count"),
        (("图表",), "图表部件数量", "chart_count"),
        (("透视表",), "透视表定义部件数量", "pivot_table_count"),
        (("表格",), "原生表格对象数量", "table_count"),
        (("隐藏",), "隐藏页面或工作表数量", "hidden_count"),
        (("批注", "注释", "评论"), "批注、注释或评论数量", "annotation_count"),
        (("图片", "图文"), "图片资源与图像对象数量", "image_count"),
        (("备注",), "演讲者备注部件数量", "notes_count"),
        (("音频", "视频"), "音视频媒体资源数量", "media_count"),
        (("切换", "转场"), "幻灯片切换效果数量", "transition_count"),
        (("页眉", "页脚"), "页眉与页脚部件数量", "header_footer_count"),
        (("工作表", "子表"), "工作表数量", "sheet_count"),
        (("build", "构建动画"), "构建动画覆盖数量", "build_count"),
        (("过滤规则", "筛选"), "过滤规则定义数量", "filter_rule_count"),
        (("模板",), "模板格式与类型识别", "is_template"),
        (("放映",), "放映文件格式与类型识别", "presentation_kind"),
        (("章节",), "文档章节结构数量", "section_count"),
    ]
    for words, label, target in patterns:
        if any(word in text for word in words):
            checks.append({"label": label, "type": "fact", "target": target,
                           "note": "先独立核定事实口径，再确认与产品 target 的映射。"})
    if declared_support == "unsupported":
        checks = [{"label": "稳定返回不支持格式", "type": "contract", "target": "UNSUPPORTED_FORMAT",
                   "note": "核验真实容器与扩展名后，再按冻结版本契约比较错误码。"}]
        summary = "未支持格式的稳定限制行为"
    elif checks:
        summary = "；".join(item["label"] for item in checks)
    else:
        summary = "该格式的代表性结构与深层探测能力"
        checks = [{"label": "代表性结构事实", "type": "fact", "target": "@all",
                   "note": "只纳入对本样本有区分度且可独立取证的事实，不机械填满全部字段。"}]
    return {"summary": summary, "checks": checks, "source": "dataset-manifest-v1"}


def _manifest(dataset):
    rows = list(csv.DictReader((dataset / "来源清单.tsv").open(encoding="utf-8"), delimiter="\t"))
    candidates = {}
    for path in dataset.rglob("*"):
        if path.is_file(): candidates.setdefault(path.name, []).append(path)
    samples = []
    for row in rows:
        matches = candidates.get(row["本地文件名"], [])
        if not matches: raise ValueError("来源清单文件缺失：" + row["本地文件名"])
        if len(matches) != 1: raise ValueError("来源清单文件名不唯一：" + row["本地文件名"])
        path = matches[0]
        source = row["来源项目"]
        if source not in SOURCE_POLICY: raise ValueError("来源许可尚未配置：" + source)
        license_name, redistributable = SOURCE_POLICY[source]
        checksum = sha(path)
        declared = "supported" if row["状态"] == "已支持" else "unsupported"
        case_id = "case-" + checksum[:20]
        relative = path.relative_to(dataset).as_posix()
        provenance = {"type": "curated-dataset", "project": source, "version": row["来源版本"],
                      "upstreamPath": row["原始路径"], "preparation": row["处理方式"],
                      "license": license_name, "redistributable": redistributable,
                      "datasetPath": relative}
        samples.append({"id": case_id, "title": path.stem, "path": str(path.resolve()),
                        "location": relative, "inputName": path.name,
                        "format": path.suffix.lstrip(".").lower(), "sha256": checksum,
                        "bytes": path.stat().st_size, "private": not redistributable,
                        "active": True, "version": 1, "answers": [],
                        "tags": [declared, source], "declaredSupport": declared,
                        "purpose": _purpose(path.name, declared),
                        "sourceRecord": {"id": case_id, "path": str(path.resolve()),
                            "format": path.suffix.lstrip(".").lower(), "sha256": checksum,
                            "bytes": path.stat().st_size, "private": not redistributable,
                            "active": True, "purpose": _purpose(path.name, declared),
                            "provenance": provenance}})
    if not samples: raise ValueError("数据集来源清单不能为空")
    if len({s["id"] for s in samples}) != len(samples): raise ValueError("数据集存在重复内容哈希")
    return samples


def _verify_checksums(dataset):
    errors = []
    for line in (dataset / "SHA256SUMS").read_text().splitlines():
        expected, separator, name = line.partition("  ")
        path = dataset / name
        if not separator or not path.is_file() or sha(path) != expected:
            errors.append(name)
    if errors: raise ValueError("数据集 SHA-256 校验失败：" + ", ".join(errors))


def onboard(dataset, home=DEFAULT_HOME, project_id=PROJECT_ID):
    dataset, home = Path(dataset).resolve(), Path(home).resolve()
    _verify_checksums(dataset)
    samples = _manifest(dataset)
    Store, _ = modules(); manager_home = home / "casework"; store = Store(manager_home)
    existing = {p["id"] for p in store.projects()}
    migration = home / "migrations" / ("dataset-" + digest([str(dataset), [s["sha256"] for s in samples]])[:16])
    migration.mkdir(parents=True, exist_ok=True)
    if store.db.is_file() and not (migration / "before.sqlite3").exists():
        shutil.copy2(store.db, migration / "before.sqlite3")
    bundle = {"schemaVersion": 1, "project": {"id": project_id,
        "name": "DeckProbe 格式测试数据集", "adapter": "deckprobe-acceptance-v2",
        "factSchema": 2, "scopeSchema": 1, "mappings": {}, "answerScopes": {},
        "samples": samples, "gaps": []}}
    refresh={"preserved":0,"added":len(samples),"removed":0,"changedBindings":0}
    if project_id not in existing:
        project = store.import_bundle(bundle)
    else:
        project = store.get(project_id)
        def clean_source(value):
            value=dict(value or {});purpose=dict(value.get('purpose') or {});purpose.pop('binding',None)
            for check in purpose.get('checks',[]):check.pop('factKey',None);check.pop('factKeys',None)
            value['purpose']=purpose;return value
        def identity_rows(rows):
            return sorted((s.get("id"),s.get("sha256"),s.get("inputName"),s.get("format"),s.get("title"),
                           s.get("private"),s.get("location"),clean_source(s.get("sourceRecord"))) for s in rows)
        current = identity_rows(project["samples"])
        incoming = identity_rows(samples)
        if current != incoming:
            atomic(migration / "before-project.json", project)
            project = store.refresh_bundle(bundle,actor="Codex · 数据集版本刷新",
                note="按来源清单刷新活动样本；内容身份未变化的 GT 保留，新增或换内容样本不继承审批。")
            refresh=project.pop('_refresh')
        else:
            refresh={"preserved":len(samples),"added":0,"removed":0,"changedBindings":0}
    # Unsupported-format expectations come from the frozen product support
    # contract plus independently verified sample identity. They remain pending.
    project = store.get(project_id)
    incoming_by_id={s['id']:s for s in samples}
    for sample in list(project['samples']):
        expected_private=incoming_by_id[sample['id']]['private']
        if sample.get('private')!=expected_private:
            project=store.act(project_id,{"action":"sample_visibility","revision":project['revision'],
                "sampleId":sample['id'],"actor":"Codex · 来源许可策略","note":"按来源再分发策略更新公开快照资格。",
                "private":expected_private})
    for sample in [s for s in project['samples'] if s.get('declaredSupport') == 'unsupported']:
        if any(a.get('check',{}).get('type') == 'error' for a in sample['answers']): continue
        project = store.act(project_id, {"action": "save_answer", "revision": project["revision"],
            "sampleId": sample["id"], "actor": "Codex · 数据集导入", "note": "建立待审的未支持格式契约。",
            "answer": {"question": "该文件在当前支持声明下应返回什么限制结果？",
                "expected": "UNSUPPORTED_FORMAT", "check": {"type": "error"},
                "options": ["-l", "deep", "-t", "@all"], "requirement": "PRO-R03",
                "evidence": {"method": "来源清单的支持状态 + 文件扩展名、魔数/容器独立核验",
                    "location": sample["location"],
                    "notes": "这是待人工审核的版本契约；DeckProbe 本次输出没有被当作答案来源。"}}})
    config = {"module": "casework", "home": str(manager_home), "project": project_id,
              "version": 2, "dataset": str(dataset), "switchedAt": now()}
    atomic(home / "maintenance.json", config)
    apply_project(home, project)
    native = read(dataset / "DeckProbe深度探测完整结果.json", {})
    observations = {"schemaVersion": 1, "role": "product-observation-not-ground-truth",
                    "datasetDigest": digest(sorted((s["id"], s["sha256"]) for s in samples)),
                    "records": [{"caseId": r.get("sample", {}).get("case_id"),
                                 "recordId": r.get("record_id"), "toolVersion": r.get("report", {}).get("tool_version"),
                                 "status": r.get("report", {}).get("status")}
                                for r in native.get("records", [])]}
    atomic(migration / "product-observations.json", observations)
    referenced={s.get('sha256') for p in store.projects() for s in store.get(p['id']).get('samples',[]) if s.get('sha256')}
    retired=migration/'retired-objects';retired_count=0
    for folder in sorted((manager_home/'objects').iterdir() if (manager_home/'objects').exists() else []):
        if not folder.is_dir() or folder.name in referenced:continue
        retired.mkdir(parents=True,exist_ok=True)
        destination=retired/folder.name
        if destination.exists():shutil.rmtree(folder)
        else:shutil.move(str(folder),str(destination))
        retired_count+=1
    summary = {"project": project_id, "samples": len(samples),
               "public": sum(not s["private"] for s in samples),
               "private": sum(s["private"] for s in samples),
               "oldProjectsPreserved": sorted(existing - {project_id}), "refresh":refresh,
               "retiredObjects":retired_count,
               "backup": str(migration / "before.sqlite3"),
               "activeExecutionProject": project_id}
    atomic(migration / "summary.json", summary)
    return summary
