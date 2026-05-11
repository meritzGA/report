"""
prizebase_YYYYMM.xlsx → data/prizebase_YYYYMM.parquet

원본 raw 엑셀(약 80MB / 115K rows / 175 cols)에서 대시보드에 필요한 컬럼만 추출하여
parquet으로 저장한다. parquet 결과는 수 MB 수준으로 깃 업로드/배포에 적합.

사용법:
    python scripts/preprocess.py                    # D:\\raw 의 4월/5월 둘 다 변환
    python scripts/preprocess.py 202605             # 특정 월만
    python scripts/preprocess.py --raw "C:/data" --out "data"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from python_calamine import CalamineWorkbook

# 대시보드에 필요한 핵심 컬럼만 유지 (4월/5월 두 파일 모두 동일하게 존재 확인됨)
KEEP_COLS = [
    "기준년월",
    "상품구분",
    "대리점설계사조직코드",
    "대리점설계사명",
    "본부조직명",       # = '전략영업총괄' 단일값 (참고용)
    "지역단조직명",      # 본부 (예: GA1본부, 충청GA본부 …)
    "지점조직명",        # 지점 (예: GA1-2지점 …)
    "영업가족명",        # 대리점(모기업) 단위
    "대리점지사명",      # 대리점지사(세부 단위)
    "본점관리조직명",    # 본점 관리 본부 (참고용)
    "본점관리지점명",    # 본점 관리 지점 (참고용)
    "입력일자",          # 영업월 마감 기준 일자 → 진도 비교 기준
    "청약일자",
    "계상일자",
    "월납환산보험료",    # 매출 지표(주)
    "보장보험료",        # 매출 지표(보조)
    "보험료",            # 매출 지표(보조)
    "건수",
    "인보험건수계",
    "자기계약여부",      # 진성 매출 필터링용(옵션)
    "취급자계약여부",
    "내근직계약여부",
]

NUMERIC_COLS = ["월납환산보험료", "보장보험료", "보험료", "건수", "인보험건수계"]
DATE_COLS = ["입력일자", "청약일자", "계상일자"]


def read_xlsx(path: Path) -> pd.DataFrame:
    print(f"[read] {path.name}", flush=True)
    wb = CalamineWorkbook.from_path(str(path))
    sheet = wb.get_sheet_by_name(wb.sheet_names[0])
    data = sheet.to_python()
    if not data:
        raise RuntimeError(f"Empty sheet in {path}")
    header = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=header)
    print(f"       rows={len(df):,} cols={len(df.columns)}", flush=True)
    return df


def slim(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in KEEP_COLS if c not in df.columns]
    if missing:
        print(f"  [warn] missing cols (kept blank): {missing}", flush=True)
        for c in missing:
            df[c] = None
    df = df[KEEP_COLS].copy()

    for c in NUMERIC_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    for c in DATE_COLS:
        df[c] = pd.to_datetime(df[c], errors="coerce")

    # 텍스트 컬럼 strip + 빈문자 → None
    text_cols = [
        c for c in df.columns
        if c not in NUMERIC_COLS + DATE_COLS
    ]
    for c in text_cols:
        df[c] = df[c].astype(str).str.strip()
        df.loc[df[c].isin(["", "nan", "None", "NaT"]), c] = None
    return df


def convert_path(src: Path, dst: Path) -> tuple[Path, int]:
    """임의의 src xlsx 경로를 dst parquet 경로로 변환. (rows 반환)"""
    src, dst = Path(src), Path(dst)
    if not src.exists():
        raise FileNotFoundError(src)
    df = read_xlsx(src)
    df = slim(df)
    dst.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dst, index=False, compression="zstd")
    print(f"[write] {dst.name}  rows={len(df):,}  size={dst.stat().st_size/1e6:.2f} MB",
          flush=True)
    return dst, len(df)


def convert_one(raw_dir: Path, out_dir: Path, ym: str) -> Path:
    src = Path(raw_dir) / f"prizebase_{ym}.xlsx"
    dst = Path(out_dir) / f"prizebase_{ym}.parquet"
    return convert_path(src, dst)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ym", nargs="*", help="대상 YYYYMM (생략 시 raw 폴더 전체)")
    ap.add_argument("--raw", default=None, help="원본 xlsx 폴더 (기본: 프로젝트 상위 폴더)")
    ap.add_argument("--out", default=None, help="parquet 저장 폴더 (기본: data/)")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    raw_dir = Path(args.raw) if args.raw else project_root.parent
    out_dir = Path(args.out) if args.out else project_root / "data"

    if args.ym:
        targets = args.ym
    else:
        targets = sorted({
            p.stem.replace("prizebase_", "")
            for p in raw_dir.glob("prizebase_*.xlsx")
        })
        if not targets:
            print(f"no prizebase_*.xlsx in {raw_dir}", file=sys.stderr)
            sys