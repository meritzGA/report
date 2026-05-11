"""
대시보드 핵심 비즈니스 로직
- 영업일 = 월~금 & (한국 공휴일 + 근로자의 날 등 추가 휴무) 제외
- 비영업일 입력분은 같은 월의 직전 영업일로 이월(roll-back)
  · 5월 file의 5/1, 5/2, 5/3 → 5월 첫 영업일 5/4 (직전 5월 영업일이 없으므로 직후로)
  · 5월 file의 5/5 (어린이날) → 5/4 (직전 5월 영업일)
  · 4월 file의 5/1~5/4 입력분 → 4월 마지막 영업일 4/30
- G/R = 5월 / 4월 - 1 (음수 가능)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import holidays
import numpy as np
import pandas as pd

HQ_COL = "지역단조직명"
BRANCH_COL = "지점조직명"
AGENCY_PARENT_COL = "영업가족명"
AGENCY_SUB_COL = "대리점지사명"
PLANNER_ID_COL = "대리점설계사조직코드"
PLANNER_NAME_COL = "대리점설계사명"
INPUT_DATE_COL = "입력일자"
EFF_BD_COL = "유효영업일"   # 비영업일 입력분을 이월(roll-back)한 effective business day
PRODUCT_KIND_COL = "상품구분"
SALES_COL = "월납환산보험료"
COUNT_COL = "건수"

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"
AgencyLevel = Literal["영업가족명", "대리점지사명"]

_KR = holidays.country_holidays("KR")

# 보험업계 추가 휴무일(법정공휴일은 아니나 업계 관행상 휴무)
EXTRA_HOLIDAYS_MMDD: set[tuple[int, int]] = {
    (5, 1),   # 근로자의 날
}

# 매칭 모드 자동 전환 임계값
# - ref_date.day < BACKWARD_MODE_FROM_DAY  → forward(월초~ref_date 누계 비교, 동영업일수)
# - ref_date.day >= BACKWARD_MODE_FROM_DAY → backward(월말~ref_date 잔여 영업일 비교)
BACKWARD_MODE_FROM_DAY = 25


def is_business_day(d) -> bool:
    ts = pd.Timestamp(d)
    if ts.weekday() >= 5:
        return False
    if (ts.month, ts.day) in EXTRA_HOLIDAYS_MMDD:
        return False
    return ts.date() not in _KR


def _file_mtime(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


def business_days_range(year: int, month: int) -> list[pd.Timestamp]:
    start = pd.Timestamp(year, month, 1)
    end = (start + pd.offsets.MonthEnd(1)).normalize()
    days = pd.date_range(start, end, freq="D")
    return [d for d in days if is_business_day(d)]


def business_days_in(df: pd.DataFrame, col: str = EFF_BD_COL) -> list[pd.Timestamp]:
    s = df[col].dropna().dt.normalize().drop_duplicates().sort_values()
    return [d for d in s if is_business_day(d)]


def _effective_business_day(input_date: pd.Timestamp,
                            month_bdays: list[pd.Timestamp]) -> pd.Timestamp | None:
    """입력일자 → 같은 월의 영업일.
    영업일이면 자기 자신, 비영업일이면 같은 월의 직전 영업일,
    직전이 없으면(=월 초 비영업일) 같은 월의 직후 영업일.
    """
    if pd.isna(input_date):
        return None
    d = pd.Timestamp(input_date).normalize()
    if not month_bdays:
        return None
    # 같은 월의 영업일에서 직전 매핑
    same_month_bdays = [b for b in month_bdays if b.month == d.month and b.year == d.year]
    if not same_month_bdays:
        # 다른 월(예: 4월 file의 5월 입력분) → 그 달의 마지막 영업일로
        prev_month_last = [b for b in month_bdays if b < d]
        return prev_month_last[-1] if prev_month_last else month_bdays[0]
    # 직전 (≤ d) 우선
    le = [b for b in same_month_bdays if b <= d]
    if le:
        return le[-1]
    # 직전 없음 → 직후
    return same_month_bdays[0]


def attach_effective_bday(df: pd.DataFrame, year: int, month: int) -> pd.DataFrame:
    """입력일자를 같은 월의 영업일에 이월한 EFF_BD_COL 컬럼을 추가/갱신.
    4월 file이라면 month=4: 4월 영업일 + 4월 file의 5월 입력분은 4월 마지막 영업일에 합산.
    """
    bdays = business_days_range(year, month)
    out = df.copy()
    out[INPUT_DATE_COL] = pd.to_datetime(out[INPUT_DATE_COL], errors="coerce")
    out[EFF_BD_COL] = out[INPUT_DATE_COL].apply(lambda d: _effective_business_day(d, bdays))
    return out


def load_month(ym: str, data_dir: Path | None = None) -> pd.DataFrame:
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    p = data_dir / f"prizebase_{ym}.parquet"
    if not p.exists():
        raise FileNotFoundError(p)
    df = pd.read_parquet(p)
    df[INPUT_DATE_COL] = pd.to_datetime(df[INPUT_DATE_COL], errors="coerce")
    year, month = int(ym[:4]), int(ym[4:])
    df = attach_effective_bday(df, year, month)
    return df


def cache_key(data_dir: Path | None = None,
              months: Iterable[str] = ("202604", "202605")) -> tuple:
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    return tuple((m, _file_mtime(data_dir / f"prizebase_{m}.parquet")) for m in months)


@dataclass
class PeriodPair:
    may_days: list[pd.Timestamp]
    apr_days: list[pd.Timestamp]
    n_days: int
    ref_date: pd.Timestamp
    mode: str = "forward"   # "forward" | "backward"

    @property
    def label(self) -> str:
        a0, aN = self.apr_days[0].date(), self.apr_days[-1].date()
        m0, mN = self.may_days[0].date(), self.may_days[-1].date()
        if self.mode == "backward":
            return (f"잔여영업일 모드 · 5월 {m0} - {mN} ({self.n_days}영업일) "
                    f"vs 4월 동기간 잔여 {a0} - {aN}")
        return (f"동영업일수 모드 · 5월 {m0} - {mN} (영업일 {self.n_days}일) "
                f"vs 4월 {a0} - {aN}")


def make_period_pair(df_apr: pd.DataFrame, df_may: pd.DataFrame,
                     ref_date: pd.Timestamp | None = None) -> PeriodPair:
    """
    매칭 모드:
    - ref_date.day < BACKWARD_MODE_FROM_DAY(=25) → forward
        5월 [첫 영업일 ~ ref_date까지 N영업일] vs 4월 [첫 N영업일]
    - ref_date.day >= 25 → backward (잔여 영업일 기준)
        5월 [ref_date ~ 5월말까지 K영업일] vs 4월 [4월말 마지막 K영업일]
        (단 K가 0이면 마지막 1영업일로 fallback)
    """
    apr_cal = business_days_range(2026, 4)
    may_cal = business_days_range(2026, 5)
    if ref_date is None:
        ref_date = may_cal[-1]
    ref_date = pd.Timestamp(ref_date).normalize()

    if ref_date.day < BACKWARD_MODE_FROM_DAY:
        # forward: 월초부터 ref_date까지 N영업일
        may_used = [d for d in may_cal if d <= ref_date]
        if not may_used:
            may_used = [may_cal[0]]
        n = len(may_used)
        apr_used = apr_cal[:n] if len(apr_cal) >= n else apr_cal
        return PeriodPair(may_days=may_used, apr_days=apr_used,
                          n_days=n, ref_date=ref_date, mode="forward")

    # backward: ref_date ~ 월말까지 K영업일
    may_used = [d for d in may_cal if d >= ref_date]
    if not may_used:
        # ref_date가 마지막 영업일 이후라면 마지막 1영업일만
        may_used = [may_cal[-1]]
    k = len(may_used)
    apr_used = apr_cal[-k:] if len(apr_cal) >= k else apr_cal
    return PeriodPair(may_days=may_used, apr_days=apr_used,
                      n_days=k, ref_date=ref_date, mode="backward")


def apply_filters(df: pd.DataFrame, hq: list[str] | None = None,
                  branch: list[str] | None = None,
                  insurance_only: bool = True) -> pd.DataFrame:
    out = df
    if hq:
        out = out[out[HQ_COL].isin(hq)]
    if branch:
        out = out[out[BRANCH_COL].isin(branch)]
    if insurance_only:
        out = out[out[PRODUCT_KIND_COL] == "인보험"]
    return out


def aggregate(df: pd.DataFrame, group_col) -> pd.DataFrame:
    if isinstance(group_col, str):
        group_col = [group_col]
    base = df.groupby(group_col, dropna=False).agg(
        매출=(SALES_COL, "sum"),
        건수=(COUNT_COL, "sum"),
    ).reset_index()
    active = (
        df[(df[PRODUCT_KIND_COL] == "인보험") & (df[SALES_COL] > 0)]
        .groupby(group_col, dropna=False)[PLANNER_ID_COL]
        .nunique().rename("가동인원").reset_index()
    )
    out = base.merge(active, on=group_col, how="left").fillna({"가동인원": 0})
    out["매출"] = out["매출"].astype(float)
    out["건수"] = out["건수"].astype(float)
    out["가동인원"] = out["가동인원"].astype(float)
    return out


def _safe_growth(num, den) -> np.ndarray:
    a = np.array([float(v) if v is not None and not pd.isna(v) else 0.0
                  for v in pd.Series(num)], dtype=float)
    b = np.array([float(v) if v is not None and not pd.isna(v) else 0.0
                  for v in pd.Series(den)], dtype=float)
    out = np.zeros_like(a)
    mask = b != 0
    out[mask] = a[mask] / b[mask] - 1.0
    return out


def _slice_by_eff_bdays(df: pd.DataFrame, days: list[pd.Timestamp]) -> pd.DataFrame:
    return df[df[EFF_BD_COL].isin(days)]


def comparison_table(df_apr, df_may, pp: PeriodPair, group_col) -> pd.DataFrame:
    apr_slice = _slice_by_eff_bdays(df_apr, pp.apr_days)
    may_slice = _slice_by_eff_bdays(df_may, pp.may_days)
    apr_g = aggregate(apr_slice, group_col).add_suffix("_4월")
    may_g = aggregate(may_slice, group_col).add_suffix("_5월")
    if isinstance(group_col, str):
        group_col = [group_col]
    apr_g = apr_g.rename(columns={f"{c}_4월": c for c in group_col})
    may_g = may_g.rename(columns={f"{c}_5월": c for c in group_col})
    merged = apr_g.merge(may_g, on=group_col, how="outer").fillna(0)
    for col in ["매출", "건수", "가동인원"]:
        a, m = f"{col}_4월", f"{col}_5월"
        if a in merged.columns and m in merged.columns:
            merged[f"{col}_Gap"] = merged[m].astype(float) - merged[a].astype(float)
            merged[f"{col}_GR%"] = _safe_growth(merged[m], merged[a]) * 100
    if "매출_5월" in merged.columns:
        merged = merged.sort_values("매출_5월", ascending=False).reset_index(drop=True)
    return merged


def daily_trend(df_apr, df_may, pp: PeriodPair) -> pd.DataFrame:
    def _cum(df, days):
        idx = list(range(1, len(days) + 1))
        slc = _slice_by_eff_bdays(df, days)
        s = (slc.groupby(EFF_BD_COL)[SALES_COL].sum()
                .reindex(days, fill_value=0))
        return pd.DataFrame({
            "영업일N": idx,
            "일자": [d.date() for d in days],
            "일매출": s.values,
            "누계매출": s.cumsum().values,
        })
    apr = _cum(df_apr, pp.apr_days).assign(월="4월")
    may = _cum(df_may, pp.may_days).assign(월="5월")
    return pd.concat([apr, may], ignore_index=True)
