#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
manifest="$script_dir/来源清单.tsv"
spreadsheetbench_temp_dir=""

cleanup() {
  if [[ -n "$spreadsheetbench_temp_dir" && -d "$spreadsheetbench_temp_dir" ]]; then
    rm -rf "$spreadsheetbench_temp_dir"
  fi
}
trap cleanup EXIT

download() {
  local url="$1"
  local destination="$2"
  mkdir -p "$(dirname "$destination")"
  if [[ -s "$destination" ]]; then
    return
  fi
  curl --proto '=https' --tlsv1.2 --fail --location --retry 3 \
    --silent --show-error --output "$destination" "$url"
}

hf_download() {
  local repo="$1"
  local revision="$2"
  local source_path="$3"
  local destination="$4"
  local encoded_path
  encoded_path="$(python3 - "$source_path" <<'PY'
import sys
from urllib.parse import quote

print(quote(sys.argv[1], safe="/"))
PY
)"
  download "https://huggingface.co/datasets/$repo/resolve/$revision/$encoded_path?download=true" "$destination"
}

while IFS=$'\t' read -r status group local_name source revision source_path method; do
  [[ "$status" == "状态" ]] && continue
  if [[ "$status" == "已支持" ]]; then
    destination="$script_dir/01_明确支持/$group/$local_name"
  else
    destination="$script_dir/02_暂未支持/$local_name"
  fi

  [[ -s "$destination" ]] && continue

  case "$source" in
    Apache_Tika)
      download "https://raw.githubusercontent.com/apache/tika/$revision/$source_path" "$destination"
      ;;
    Apache_POI)
      download "https://raw.githubusercontent.com/apache/poi/$revision/$source_path" "$destination"
      ;;
    delivr_to_file_samples)
      download "https://raw.githubusercontent.com/delivr-to/file-samples/$revision/$source_path" "$destination"
      ;;
    OmniDocBench)
      temp_dir="$(mktemp -d /tmp/omnidocbench.XXXXXX)"
      image_path="$temp_dir/source.png"
      converter_path="$temp_dir/image_to_pdf.py"
      download "https://huggingface.co/datasets/opendatalab/OmniDocBench/resolve/$revision/$source_path" "$image_path"
      download "https://raw.githubusercontent.com/opendatalab/OmniDocBench/193627ae9e97d89188468ed1ee3b7a856ff76044/tools/image_to_pdf.py" "$converter_path"
      mkdir -p "$(dirname "$destination")"
      python3 - "$converter_path" "$image_path" "$destination" <<'PY'
import importlib.util
import sys

converter_path, image_path, destination = sys.argv[1:]
spec = importlib.util.spec_from_file_location("omnidocbench_image_to_pdf", converter_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.image_to_pdf(image_path, destination)
PY
      ;;
    cupertino_files)
      download "https://raw.githubusercontent.com/den-frie-vilje/cupertino-files/$revision/$source_path" "$destination"
      ;;
    HuggingFace_OmegaUse_OfficeVal)
      hf_download "baidu-frontier-research/OmegaUse-OfficeVal" "$revision" "$source_path" "$destination"
      ;;
    HuggingFace_Zenodo10K)
      hf_download "Forceless/Zenodo10K" "$revision" "$source_path" "$destination"
      ;;
    HuggingFace_OfficeComprehensionBenchmark)
      hf_download "microsoft/OfficeComprehensionBenchmark" "$revision" "$source_path" "$destination"
      ;;
    HuggingFace_SpreadsheetBench)
      if [[ -z "$spreadsheetbench_temp_dir" ]]; then
        spreadsheetbench_temp_dir="$(mktemp -d /tmp/spreadsheetbench.XXXXXX)"
        hf_download "KAKA22/SpreadsheetBench" "$revision" "spreadsheetbench_verified_400.tar.gz" "$spreadsheetbench_temp_dir/source.tar.gz"
      fi
      mkdir -p "$(dirname "$destination")"
      tar -xOzf "$spreadsheetbench_temp_dir/source.tar.gz" "$source_path" > "$destination"
      ;;
    *)
      echo "未知来源: $source" >&2
      exit 1
      ;;
  esac
done < "$manifest"
