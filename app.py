"""
대리점 진도 대시보드 (Streamlit Cloud · 모바일 최적화)
- 비밀번호 게이트
- 필터 상단, 사이드바 미사용
- 첫 컬럼(대리점명) 틀고정
- expander 화살표는 폰트 의존성 없이 CSS triangle로 그림
- 데스크탑은 Streamlit 기본 레이아웃 유지, 모바일만 추가 조정
"""
from __future__ import annotations

import sys
import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st

from data_logic import (
    AGENCY_PARENT_COL, AGENCY_SUB_COL, BRANCH_COL, HQ_COL, SALES_COL,
    apply_filters, attach_effective_bday, business_days_range, cache_key,
    comparison_table, daily_trend, load_month, make_period_pair,
)

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
from preprocess import convert_path  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"

TOP_N_SUB_AGENCY = 200
EFF_BD = "유효영업일"


def _get_password() -> str:
    try:
        if "password" in st.secrets:
            return str(st.secrets["password"])
    except Exception:
        pass
    return "0505"

PASSWORD = _get_password()

st.set_page_config(
    page_title="대리점 진도 대시보드",
    layout="wide",
    initial_sidebar_state="collapsed",
)

_CSS = """<style>
@import url('https://fonts.googleapis.com/icon?family=Material+Icons');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded');

/* Streamlit Cloud 상단 헤더(deploy bar)가 콘텐츠를 가리지 않게 충분한 여백 확보 */
.block-container { padding-top: 4rem !important; }
/* 상단 헤더 자체를 불투명하게 → 스크롤 시 콘텐츠와 겹쳐도 흐려 보이지 않음 */
[data-testid="stHeader"] { background: white !important; }

[data-testid="collapsedControl"] { display:none; }

[data-testid="stIconMaterial"], .material-symbols-rounded, .material-symbols-outlined, .material-icons {
  font-family:'Material Symbols Rounded','Material Symbols Outlined','Material Icons',sans-serif !important;
  font-feature-settings:'liga' !important;
}

[data-testid="stExpander"] summary [data-testid="stIconMaterial"] {
  font-size:0 !important; color:transparent !important;
  position:relative; width:1rem; height:1rem; overflow:hidden;
}
[data-testid="stExpander"] summary [data-testid="stIconMaterial"]::after {
  content:''; position:absolute; left:50%; top:50%;
  transform:translate(-50%,-50%); width:0; height:0;
  border-left:5px solid transparent; border-right:5px solid transparent;
  border-top:6px solid currentColor; transition:transform 0.15s;
}
[data-testid="stExpander"] details[open] summary [data-testid="stIconMaterial"]::after {
  transform:translate(-50%,-50%) rotate(180deg);
}

div[data-testid="stDataFrame"] table th:first-child,
div[data-testid="stDataFrame"] table td:first-child {
  position:sticky; left:0; background:var(--background-color,white);
  z-index:2; box-shadow:2px 0 4px rgba(0,0,0,0.05);
}
details summary { padding-right:32px; }

@media (max-width: 768px) {
  .block-container {
    padding-top: 2rem !important;
    padding-left: 0.7rem !important;
    padding-right: 0.7rem !important;
  }
  h1 { font-size:1.4rem !important; }
  h2 { font-size:1.1rem !important; }
}
</style>"""

try:
    st.html(_CSS)
except Exception:
    st.markdown(_CSS, unsafe_allow_html=True)


def _check_password():
    if st.session_state.get("auth_ok"):
        return
    st.title("대리점 진도 대시보드")
    st.caption("비밀번호를 입력하세요.")
    with st.form("login_form"):
        pw = st.text_input("비밀번호", type="password",
                           label_visibility="collapsed", placeholder="비밀번호")
        ok = st.form_submit_button("입장", width="stretch", type="primary")
    if ok:
        if pw == PASSWORD:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("비밀번호가 일치하지 않습니다.")
    st.stop()


@st.cache_data(show_spinner="데이터 로딩 중...")
def _load(_key):
    return load_month("202604"), load_month("202605")


def get_data():
    return _load(cache_key())


def _ensure_eff(df, year, month):
    if EFF_BD not in df.columns:
        return attach_effective_bday(df, year, month)
    return df


def _fmt_table(df, key_col):
    show = df.copy()
    int_cols = [c for c in show.columns
                if c.startswith(("매출_", "건수_", "가동인원_")) and not c.endswith("GR%")]
    for c in int_cols:
        show[c] = show[c].astype(float).round(0).astype("Int64")
    for c in [c for c in show.columns if c.endswith("GR%")]:
        show[c] = show[c].astype(float).round(1)
    order = [key_col]
    for m in ["매출", "건수", "가동인원"]:
        order += [f"{m}_4월", f"{m}_5월", f"{m}_Gap", f"{m}_GR%"]
    return show[[c for c in order if c in show.columns]]


def _build_styler(df, key_col):
    show = _fmt_table(df, key_col).set_index(key_col)
    fmt = {c: "{:,.0f}" for c in show.columns
           if c.startswith(("매출_", "건수_", "가동인원_")) and not c.endswith("GR%")}
    fmt.update({c: "{:+.1f}%" for c in show.columns if c.endswith("GR%")})
    sty = show.style.format(fmt, na_rep="-")
    for c in [c for c in show.columns if c.endswith("GR%")]:
        sty = sty.background_gradient(subset=[c], cmap="RdYlGn", vmin=-50, vmax=50)
    for c in [c for c in show.columns if c.endswith("Gap")]:
        sty = sty.map(
            lambda v: "color: #c0392b" if isinstance(v, (int, float)) and v < 0
            else ("color: #27ae60" if isinstance(v, (int, float)) and v > 0 else ""),
            subset=[c])
    sty = sty.set_sticky(axis=0)
    return sty


def _show_table(df, key_col, height=540):
    sty = _build_styler(df, key_col)
    try:
        st.dataframe(
            sty, width="stretch", height=height,
            column_config={"_index": st.column_config.Column(pinned=True, width="medium")},
        )
    except Exception:
        st.dataframe(sty, width="stretch", height=height)


def _kpi(apr_p, may_p, label="전체"):
    aps = apr_p[SALES_COL].sum()
    mps = may_p[SALES_COL].sum()
    apa = apr_p[apr_p[SALES_COL] > 0]["대리점설계사조직코드"].nunique()
    mpa = may_p[may_p[SALES_COL] > 0]["대리점설계사조직코드"].nunique()
    gap = mps - aps
    gr = (mps / aps - 1) * 100 if aps else 0.0
    agr = (mpa / apa - 1) * 100 if apa else 0.0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(f"4월 동기간 ({label})", f"{aps/1e8:,.2f} 억")
    c2.metric(f"5월 누계 ({label})", f"{mps/1e8:,.2f} 억", delta=f"{gap/1e8:+.2f} 억")
    c3.metric("매출 G/R", f"{gr:+.1f}%")
    c4.metric("가동인원 (5월/4월)", f"{mpa:,} / {apa:,}", delta=f"{mpa-apa:+,}")
    c5.metric("가동인원 G/R", f"{agr:+.1f}%")


def _render_update_panel():
    may_pq = DATA_DIR / "prizebase_202605.parquet"
    if may_pq.exists():
        ts = pd.Timestamp(may_pq.stat().st_mtime, unit="s")
        st.caption(f"현재 5월 데이터: **{ts:%Y-%m-%d %H:%M}**")
    st.caption("새 5월 데이터(xlsx)를 끌어다 놓으면 즉시 반영됩니다.")
    up = st.file_uploader("prizebase_202605.xlsx", type=["xlsx"],
                          key="may_upload", label_visibility="collapsed")
    if up is not None and st.button("업로드 파일로 갱신",
                                     width="stretch", type="primary"):
        tmp = DATA_DIR / "_upload_202605.xlsx"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(up.getbuffer())
        try:
            with st.spinner("처리 중..."):
                _, rows = convert_path(tmp, may_pq)
            st.cache_data.clear()
            st.success(f"{rows:,}건 처리 완료")
            tmp.unlink(missing_ok=True)
            st.rerun()
        except Exception as e:
            st.error(f"실패: {e}")
            tmp.unlink(missing_ok=True)


def main():
    _check_password()

    top_l, top_r = st.columns([3, 1])
    with top_l:
        st.title("대리점 진도 대시보드")
        st.caption("4월 동영업일수 vs 5월 누계 · 인보험 기준")
    with top_r:
        if st.button("로그아웃", width="stretch"):
            st.session_state["auth_ok"] = False
            st.rerun()

    df_apr, df_may = get_data()
    df_apr = _ensure_eff(df_apr, 2026, 4)
    df_may = _ensure_eff(df_may, 2026, 5)

    with st.expander("데이터 갱신", expanded=False):
        _render_update_panel()

    with st.expander("필터", expanded=True):
        may_cal = business_days_range(2026, 5)
        default_ref = may_cal[-1].date()
        if EFF_BD in df_may.columns:
            mapped = sorted(df_may[EFF_BD].dropna().dt.normalize().unique())
            if mapped:
                default_ref = pd.Timestamp(mapped[-1]).date()

        f1, f2 = st.columns(2)
        with f1:
            ref = st.date_input(
                "기준일 (5월)",
                value=default_ref,
                min_value=dt.date(2026, 5, 1),
                max_value=dt.date(2026, 5, 31),
                format="YYYY-MM-DD",
                help="기준일 24일 이하: 동영업일수, 25일 이상: 잔여영업일",
            )
            hq_opts = sorted(df_apr[HQ_COL].dropna().unique().tolist())
            hq_sel = st.multiselect("본부", hq_opts, placeholder="전체")
        with f2:
            bp = df_apr if not hq_sel else df_apr[df_apr[HQ_COL].isin(hq_sel)]
            br_opts = sorted(bp[BRANCH_COL].dropna().unique().tolist())
            br_sel = st.multiselect("지점", br_opts, placeholder="전체")
            ag_lvl = st.radio(
                "대리점 단위",
                options=[AGENCY_PARENT_COL, AGENCY_SUB_COL],
                format_func=lambda x: "영업가족명 (모기업)" if x == AGENCY_PARENT_COL
                                                      else f"대리점지사명 (Top {TOP_N_SUB_AGENCY})",
                horizontal=True,
            )

    pp = make_period_pair(df_apr, df_may, ref_date=pd.Timestamp(ref))
    st.info(f"비교 기간: **{pp.label}**")

    apr_f = apply_filters(df_apr, hq=hq_sel, branch=br_sel, insurance_only=True)
    may_f = apply_filters(df_may, hq=hq_sel, branch=br_sel, insurance_only=True)
    apr_p = apr_f[apr_f[EFF_BD].isin(pp.apr_days)]
    may_p = may_f[may_f[EFF_BD].isin(pp.may_days)]

    parts = []
    if hq_sel: parts.append("/".join(hq_sel))
    if br_sel: parts.append("/".join(br_sel[:3]) + ("..." if len(br_sel) > 3 else ""))
    if not parts: parts.append("전체")
    _kpi(apr_p, may_p, label="/".join(parts))
    st.divider()

    t1, t2, t3, t4 = st.tabs(["대리점별", "본부별", "지점별", "일별 추이"])

    with t1:
        df_t = comparison_table(apr_f, may_f, pp, ag_lvl)
        total_n = len(df_t)
        if ag_lvl == AGENCY_SUB_COL and total_n > TOP_N_SUB_AGENCY:
            df_t = df_t.head(TOP_N_SUB_AGENCY)
            st.caption(f"전체 {total_n:,}개 중 5월 매출 상위 {TOP_N_SUB_AGENCY}개")
        else:
            st.caption(f"총 {total_n:,} 개")
        q = st.text_input("대리점명 검색", "", key="ag_q",
                          label_visibility="collapsed",
                          placeholder="대리점명 검색 (부분일치)")
        if q:
            df_t = df_t[df_t[ag_lvl].astype(str).str.contains(q, na=False, case=False)]
        _show_table(df_t, ag_lvl)
        st.download_button("CSV 다운로드", df_t.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"agency_{ag_lvl}_{pp.ref_date.date()}.csv",
                           mime="text/csv")

    with t2:
        _show_table(comparison_table(apr_f, may_f, pp, HQ_COL), HQ_COL, height=420)

    with t3:
        df_t = comparison_table(apr_f, may_f, pp, BRANCH_COL)
        st.caption(f"총 {len(df_t):,} 개 지점")
        _show_table(df_t, BRANCH_COL)

    with t4:
        trend = daily_trend(apr_f, may_f, pp)
        pivot = trend.pivot(index="영업일N", columns="월", values="누계매출")
        st.line_chart(pivot, height=320)
        st.dataframe(trend, width="stretch", hide_index=True)

    st.divider()
    cap = []
    for ym, lbl in [("202604", "4월"), ("202605", "5월")]:
        p = DATA_DIR / f"prizebase_{ym}.parquet"
        if p.exists():
            cap.append(f"{lbl}: {pd.Timestamp(p.stat().st_mtime, unit='s'):%Y-%m-%d %H:%M}")
    st.caption("데이터 갱신 시각 · " + " · ".join(cap))


if __name__ == "__main__":
    main()
