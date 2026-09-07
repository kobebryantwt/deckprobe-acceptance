#!/usr/bin/env python3
"""Independent, narrow oracle helper for reproducible benchmark annotations."""

from __future__ import annotations

import argparse
import json
import plistlib
import struct
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path
from posixpath import normpath


CORE = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"
DCTERMS = "http://purl.org/dc/terms/"
CP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def text(root: ET.Element, namespace: str, name: str) -> str | None:
    node = root.find(f"{{{namespace}}}{name}")
    return node.text if node is not None else None


def ooxml_common(archive: zipfile.ZipFile, names: list[str]) -> dict:
    facts: dict = {}
    if "docProps/core.xml" in names:
        root = ET.fromstring(archive.read("docProps/core.xml"))
        facts["coreProperties"] = {
            key: text(root, namespace, tag)
            for key, namespace, tag in (
                ("title", DC, "title"), ("subject", DC, "subject"), ("author", DC, "creator"),
                ("keywords", CORE, "keywords"), ("description", DC, "description"),
                ("createdAt", DCTERMS, "created"), ("modifiedAt", DCTERMS, "modified"),
                ("lastModifiedBy", CORE, "lastModifiedBy"),
            ) if text(root, namespace, tag) is not None
        }
    if "docProps/app.xml" in names:
        root = ET.fromstring(archive.read("docProps/app.xml"))
        facts["application"] = text(root, CP, "Application")
        facts["applicationVersion"] = text(root, CP, "AppVersion")
    relationship_files = [name for name in names if name.endswith(".rels")]
    external = []
    missing_internal = []
    name_set = set(names)
    for name in relationship_files:
        root = ET.fromstring(archive.read(name))
        for node in root.findall(f"{{{REL}}}Relationship"):
            target_value = node.attrib.get("Target", "")
            if node.attrib.get("TargetMode") == "External":
                external.append({"part": name, "type": node.attrib.get("Type"), "target": target_value})
                continue
            if name == "_rels/.rels":
                base = ""
            else:
                rel_parent = Path(name).parent.parent.as_posix()
                source_name = Path(name).name.removesuffix(".rels")
                base = f"{rel_parent}/{source_name}" if rel_parent != "." else source_name
                base = str(Path(base).parent).replace(".", "")
            resolved = normpath(f"{base}/{target_value}").lstrip("/")
            if target_value and resolved not in name_set:
                missing_internal.append({"part": name, "target": target_value, "resolved": resolved})
    facts.update({
        "externalRelationships": external,
        "externalRelationshipCount": len(external),
        "missingInternalRelationships": missing_internal,
        "missingInternalRelationshipCount": len(missing_internal),
        "hasMacros": any(Path(name).name.lower() == "vbaproject.bin" for name in names),
        "signaturePartCount": sum(name.startswith("_xmlsignatures/") and not name.endswith("/") for name in names),
        "embeddedEntryCount": sum("/embeddings/" in name and not name.endswith("/") for name in names),
        "uniqueImageAssetCount": sum(
            "/media/" in name and Path(name).suffix.lower() in
            {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".svg", ".webp", ".emf", ".wmf", ".heic"}
            for name in names
        ),
        "conformance": "strict" if any("purl.oclc.org/ooxml" in archive.read(name).decode("utf-8", "ignore") for name in names if name.endswith(".xml")) else "transitional",
    })
    return facts


def zip_facts(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        detected_profile = (
            "docx" if "word/document.xml" in names else
            "pptx" if "ppt/presentation.xml" in names else
            "xlsx" if "xl/workbook.xml" in names else
            path.suffix.lower().lstrip(".")
        )
        facts = {
            "entryCount": len(names),
            "iwaEntryCount": sum(name.endswith(".iwa") for name in names),
            "hasPreview": any(Path(name).name.lower().startswith("preview.") for name in names),
            "detectedProfile": detected_profile,
        }
        if detected_profile in {"docx", "pptx", "xlsx"}:
            facts.update(ooxml_common(archive, names))
        if detected_profile == "docx":
            app = ET.fromstring(archive.read("docProps/app.xml"))
            ns = {"e": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"}
            for key in ("Pages", "Words", "Characters"):
                value = app.findtext(f"e:{key}", namespaces=ns)
                if value is not None:
                    facts[key.lower()] = int(value)
            document = ET.fromstring(archive.read("word/document.xml"))
            word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            facts["paragraphs"] = len(document.findall(f".//{word}p"))
            facts["tables"] = len(document.findall(f".//{word}tbl"))
            facts["commentPartCount"] = sum(Path(name).name.startswith("comments") and name.endswith(".xml") for name in names)
        elif detected_profile == "pptx":
            presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
            power_point = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
            facts["slides"] = len(presentation.findall(f".//{power_point}sldId"))
            facts["hiddenSlides"] = sum(node.attrib.get("show") == "0" for node in presentation.findall(f".//{power_point}sldId"))
            size = presentation.find(f".//{power_point}sldSz")
            facts["slideSizeEmu"] = {"width": int(size.attrib["cx"]), "height": int(size.attrib["cy"])}
            facts["masterCount"] = sum(name.startswith("ppt/slideMasters/slideMaster") and name.endswith(".xml") for name in names)
            facts["layoutCount"] = sum(name.startswith("ppt/slideLayouts/slideLayout") and name.endswith(".xml") for name in names)
            facts["notesSlideCount"] = sum(name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml") for name in names)
            facts["chartPartCount"] = sum(name.startswith("ppt/charts/chart") and name.endswith(".xml") for name in names)
            facts["commentPartCount"] = sum(name.startswith("ppt/comments/comment") and name.endswith(".xml") for name in names)
            media_extensions = {".mp3", ".mp4", ".m4a", ".mov", ".wav", ".avi", ".wmv", ".mpeg", ".mpg"}
            facts["mediaAssetCount"] = sum(name.startswith("ppt/media/") and Path(name).suffix.lower() in media_extensions for name in names)
            slide_parts = [name for name in names if name.startswith("ppt/slides/slide") and name.endswith(".xml")]
            slides_with_transitions = 0
            slides_with_timing = 0
            for name in slide_parts:
                slide = ET.fromstring(archive.read(name))
                slides_with_transitions += slide.find(f".//{power_point}transition") is not None
                slides_with_timing += slide.find(f".//{power_point}timing") is not None
            facts["slidesWithTransitions"] = slides_with_transitions
            facts["slidesWithTiming"] = slides_with_timing
        elif detected_profile == "xlsx":
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            sheet_ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            sheets = workbook.findall(f".//{sheet_ns}sheet")
            facts["sheetNames"] = [sheet.attrib["name"] for sheet in sheets]
            facts["hiddenSheetCount"] = sum(sheet.attrib.get("state") in {"hidden", "veryHidden"} for sheet in sheets)
            defined_names = workbook.find(f".//{sheet_ns}definedNames")
            facts["definedNameCount"] = len(list(defined_names)) if defined_names is not None else 0
            facts["sharedStringCount"] = 0
            if "xl/sharedStrings.xml" in names:
                shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                facts["sharedStringCount"] = int(shared.attrib.get("uniqueCount", len(list(shared))))
            facts["tableCount"] = sum(name.startswith("xl/tables/table") and name.endswith(".xml") for name in names)
            facts["chartPartCount"] = sum(name.startswith("xl/charts/chart") and name.endswith(".xml") for name in names)
            facts["pivotTablePartCount"] = sum(name.startswith("xl/pivotTables/pivotTable") and name.endswith(".xml") for name in names)
        elif detected_profile in {"key", "numbers", "pages"}:
            properties = plistlib.loads(archive.read("Metadata/Properties.plist"))
            facts["fileFormatVersion"] = properties.get("fileFormatVersion")
            facts["isMultiPage"] = bool(properties.get("isMultiPage"))
            external = properties.get("hasExternalReferenceOrMissingData")
            facts["hasExternalOrMissingData"] = None if external is None else bool(external)
            history = plistlib.loads(archive.read("Metadata/BuildVersionHistory.plist"))
            facts["producerBuild"] = history[-1] if isinstance(history, list) and history else None
            data_entries = [name for name in names if name.startswith("Data/") and not name.endswith("/")]
            facts["dataAssetCount"] = len(data_entries)
            facts["dataAssetBytes"] = sum(archive.getinfo(name).file_size for name in data_entries)
            image_ext = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".heic", ".webp"}
            audio_ext = {".mp3", ".m4a", ".wav", ".aac", ".aiff"}
            video_ext = {".mp4", ".mov", ".m4v", ".avi"}
            font_ext = {".ttf", ".otf", ".woff", ".woff2"}
            counts = {"image": 0, "audio": 0, "video": 0, "font": 0, "other": 0}
            for name in data_entries:
                suffix = Path(name).suffix.lower()
                kind = "image" if suffix in image_ext else "audio" if suffix in audio_ext else "video" if suffix in video_ext else "font" if suffix in font_ext else "other"
                counts[kind] += 1
            facts["assetTypeCounts"] = counts
            previews = [name for name in names if Path(name).name.lower().startswith("preview") and Path(name).suffix.lower() in image_ext]
            facts["previewCount"] = len(previews)
            try:
                from PIL import Image
                facts["previewDimensions"] = {}
                for name in previews:
                    with Image.open(BytesIO(archive.read(name))) as image:
                        facts["previewDimensions"][Path(name).name] = {"width": image.width, "height": image.height}
            except ImportError:
                pass
        return facts


def inspect(path: Path) -> dict:
    magic = path.read_bytes()[:8]
    if magic != bytes.fromhex("d0cf11e0a1b11ae1") and zipfile.is_zipfile(path):
        return {"method": "python-stdlib-zip-xml-plist", "facts": zip_facts(path)}
    if path.suffix.lower() == ".pdf":
        output = subprocess.check_output(["pdfinfo", str(path)], text=True)
        fields = {}
        for line in output.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        try:
            from collections import Counter
            from pypdf import PdfReader

            reader = PdfReader(path, strict=True)
            annotations = []
            internal_links = 0
            external_links = 0
            for page in reader.pages:
                for reference in page.get("/Annots", []):
                    annotation = reference.get_object()
                    subtype = str(annotation.get("/Subtype"))
                    annotations.append(subtype)
                    if subtype == "/Link":
                        action = annotation.get("/A")
                        if annotation.get("/Dest") is not None:
                            internal_links += 1
                        elif action and str(action.get("/S")) in {"/URI", "/GoToR", "/Launch"}:
                            external_links += 1
            form_fields = reader.get_fields() or {}
            signature_fields = [value for value in form_fields.values() if str(value.get("/FT")) == "/Sig"]
            raw = path.read_bytes()
            pypdf_facts = {
                "pageCount": len(reader.pages),
                "objectCount": sum(len(entries) for entries in reader.xref.values()),
                "xrefType": "table" if b"\nxref\n" in raw and b"/Type /XRef" not in raw else "stream-or-hybrid",
                "linearized": b"/Linearized" in raw[:2048],
                "encrypted": reader.is_encrypted,
                "annotationCount": len(annotations),
                "annotationSubtypes": dict(Counter(annotations)),
                "internalLinkCount": internal_links,
                "externalLinkCount": external_links,
                "logicalFormFieldCount": len(form_fields),
                "signatureFieldCount": len(signature_fields),
                "signedSignatureCount": sum(value.get("/V") is not None for value in signature_fields),
                "attachmentCount": len(reader.attachments),
                "attachmentNames": sorted(reader.attachments),
                "hasXmp": reader.xmp_metadata is not None,
            }
            return {"method": "pdfinfo+pypdf+raw-pdf", "facts": {"pdfinfo": fields, "pypdf": pypdf_facts}}
        except ImportError:
            return {"method": "pdfinfo", "facts": {"pdfinfo": fields, "warning": "pypdf unavailable"}}
    output = subprocess.check_output(["file", "-b", str(path)], text=True).strip()
    facts = {"description": output}
    if magic == bytes.fromhex("d0cf11e0a1b11ae1"):
        raw = path.read_bytes()
        sector_size = 1 << struct.unpack_from("<H", raw, 30)[0]
        first_directory = struct.unpack_from("<I", raw, 48)[0]
        fat_sector_ids = [sid for sid in struct.unpack_from("<109I", raw, 76) if sid < 0xFFFFFFF0]
        fat: list[int] = []
        for sid in fat_sector_ids:
            offset = (sid + 1) * sector_size
            fat.extend(struct.unpack_from(f"<{sector_size // 4}I", raw, offset))
        directory_bytes = bytearray()
        sid = first_directory
        seen = set()
        while sid < 0xFFFFFFF0 and sid not in seen and sid < len(fat):
            seen.add(sid)
            offset = (sid + 1) * sector_size
            directory_bytes.extend(raw[offset:offset + sector_size])
            sid = fat[sid]
        entries = []
        for offset in range(0, len(directory_bytes), 128):
            row = directory_bytes[offset:offset + 128]
            if len(row) < 128 or row[66] == 0:
                continue
            name_bytes = min(struct.unpack_from("<H", row, 64)[0], 64)
            name = row[:max(0, name_bytes - 2)].decode("utf-16le", errors="replace")
            entries.append({"name": name, "type": row[66]})
        facts.update({"cfbSectorSize": sector_size, "cfbEntryCount": len(entries), "cfbEntries": entries})
    return {"method": "file+independent-cfb-directory", "facts": facts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    print(json.dumps({"source": str(args.source.resolve()), **inspect(args.source)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
