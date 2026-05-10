import streamlit as st
import pyomo.environ as pyo
from pyomo.opt import TerminationCondition
import pandas as pd
import plotly.graph_objects as go

# ─────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────
st.set_page_config(
    page_title="총괄생산계획 최적화",
    layout="wide",
    page_icon="🏭"
)

st.markdown("""
<style>
    .main-title {
        font-size:2.2rem;
        font-weight:800;
        color:#1a1a2e;
        margin-bottom:0.2rem;
    }
    .sub-title {
        font-size:1rem;
        color:#555;
        margin-bottom:1.5rem;
    }
    .kpi-box {
        background: linear-gradient(135deg,#1a1a2e,#16213e);
        color:white;
        border-radius:12px;
        padding:1rem 1.2rem;
        text-align:center;
    }
    .kpi-label {
        font-size:0.8rem;
        opacity:0.7;
    }
    .kpi-value {
        font-size:1.55rem;
        font-weight:700;
    }
    .status-ok {
        background:#d4edda;
        color:#155724;
        border-radius:8px;
        padding:0.5rem 1rem;
        margin:0.3rem 0;
    }
    .status-warn {
        background:#fff3cd;
        color:#856404;
        border-radius:8px;
        padding:0.5rem 1rem;
        margin:0.3rem 0;
    }
    .status-bad {
        background:#f8d7da;
        color:#721c24;
        border-radius:8px;
        padding:0.5rem 1rem;
        margin:0.3rem 0;
    }
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<div class="main-title">🏭 총괄생산계획 최적화 시스템</div>',
    unsafe_allow_html=True
)
st.markdown(
    '<div class="sub-title">Pyomo 기반 Aggregate Production Planning (APP) | 원예장비 제조업체</div>',
    unsafe_allow_html=True
)

# ─────────────────────────────────────────
# 사이드바 입력
# ─────────────────────────────────────────
st.sidebar.header("⚙️ 파라미터 설정")

st.sidebar.subheader("📅 계획 기간")
num_months = st.sidebar.selectbox("계획 기간 (개월)", [6, 8, 12], index=0)
month_labels = [f"{i+1}월" for i in range(num_months)]

default_demands = [1600, 3000, 3200, 3800, 2200, 2200, 2500, 2800, 3000, 2700, 2400, 2100]

st.sidebar.subheader("📦 월별 예상수요 (개/월)")
demands = []
for i in range(num_months):
    d = st.sidebar.number_input(
        month_labels[i],
        min_value=0,
        value=default_demands[i] if i < len(default_demands) else 2000,
        step=100,
        key=f"d_{i}"
    )
    demands.append(d)

st.sidebar.subheader("👷 인력 파라미터")
w0 = st.sidebar.number_input("초기 근로자 수 (명)", min_value=1, value=80)
reg_wage = st.sidebar.number_input("정규임금 (천원/시간)", min_value=1, value=4)
ot_wage = st.sidebar.number_input("초과임금 (천원/시간)", min_value=1, value=6)
hire_cost = st.sidebar.number_input("고용비용 (천원/인)", min_value=0, value=300)
fire_cost = st.sidebar.number_input("해고비용 (천원/인)", min_value=0, value=500)
work_days = st.sidebar.number_input("작업일수 (일/월)", min_value=1, value=20)
work_hrs = st.sidebar.number_input("작업시간 (시간/일)", min_value=1, value=8)
max_ot = st.sidebar.number_input("초과시간 제한 (시간/인/월)", min_value=0, value=10)

st.sidebar.subheader("📦 재고 파라미터")
i0 = st.sidebar.number_input("초기 재고 (개)", min_value=0, value=1000)
i_final = st.sidebar.number_input("최종 목표재고 (개)", min_value=0, value=500)
hold_cost = st.sidebar.number_input("재고유지비 (천원/개/월)", min_value=0, value=2)
back_cost = st.sidebar.number_input("부재고비용 (천원/개/월)", min_value=0, value=5)
allow_backorder = st.sidebar.checkbox(
    "부족재고 허용",
    value=True,
    help="체크하면 부족재고를 허용하고 부재고비용을 부과합니다. 체크 해제 시 부족재고가 발생하지 않도록 제한합니다."
)

st.sidebar.subheader("🏭 생산 파라미터")
std_time = st.sidebar.number_input("작업표준시간 (시간/개)", min_value=0.1, value=4.0, step=0.5)
mat_cost = st.sidebar.number_input("재료비 (천원/개)", min_value=0, value=10)
sub_cost = st.sidebar.number_input(
    "하청비용 (천원/개)",
    min_value=0,
    value=30,
    help="하청비용은 하청 생산 1개당 발생하는 비용입니다. 재료까지 포함한 총 하청단가로 해석할 수 있습니다."
)

st.sidebar.subheader("🔧 최적화 방법")
model_type = st.sidebar.radio(
    "모델 유형",
    ["LP (선형계획법)", "IP (인력 정수계획 모형)"],
    help="LP: 모든 변수 실수 / IP: 인력 변수(W,H,L)를 정수로 처리"
)
type_mp = "IP" if "IP" in model_type else "LP"

st.sidebar.subheader("🔄 시나리오 비교")
run_both = st.sidebar.checkbox("LP & IP 동시 비교", value=False)

# ─────────────────────────────────────────
# 최적화 함수
# ─────────────────────────────────────────
def solve_app(
    demands, w0, i0, i_final,
    reg_wage, ot_wage, hire_cost, fire_cost,
    hold_cost, back_cost, mat_cost, sub_cost,
    work_days, work_hrs, max_ot, std_time, type_mp,
    allow_backorder
):
    TH = len(demands)
    TIME = range(0, TH + 1)
    T = range(1, TH + 1)

    dtype = pyo.NonNegativeIntegers if type_mp == "IP" else pyo.NonNegativeReals

    m = pyo.ConcreteModel()

    # 결정변수
    m.W = pyo.Var(TIME, domain=dtype, bounds=(0, None))
    m.H = pyo.Var(TIME, domain=dtype, bounds=(0, None))
    m.L = pyo.Var(TIME, domain=dtype, bounds=(0, None))
    m.P = pyo.Var(TIME, domain=pyo.NonNegativeReals, bounds=(0, None))
    m.I = pyo.Var(TIME, domain=pyo.NonNegativeReals, bounds=(0, None))
    if allow_backorder:
        m.S = pyo.Var(TIME, domain=pyo.NonNegativeReals, bounds=(0, None))
    else:
        m.S = pyo.Var(TIME, domain=pyo.NonNegativeReals, bounds=(0, 0))
    m.C = pyo.Var(TIME, domain=pyo.NonNegativeReals, bounds=(0, None))
    m.O = pyo.Var(TIME, domain=pyo.NonNegativeReals, bounds=(0, None))

    prod_pw = (1 / std_time) * work_hrs * work_days
    reg_cost_pw = reg_wage * work_hrs * work_days

    # 목적함수
    m.Cost = pyo.Objective(
        expr=sum(
            reg_cost_pw * m.W[t]
            + ot_wage * m.O[t]
            + hire_cost * m.H[t]
            + fire_cost * m.L[t]
            + hold_cost * m.I[t]
            + back_cost * m.S[t]
            + mat_cost * m.P[t]
            + sub_cost * m.C[t]
            for t in T
        ),
        sense=pyo.minimize
    )

    # 제약조건
    m.labor = pyo.Constraint(T, rule=lambda m, t: m.W[t] == m.W[t-1] + m.H[t] - m.L[t])
    m.capacity = pyo.Constraint(T, rule=lambda m, t: m.P[t] <= prod_pw * m.W[t] + m.O[t] / std_time)
    m.inventory = pyo.Constraint(
        T,
        rule=lambda m, t: m.I[t] == m.I[t-1] + m.P[t] + m.C[t] - demands[t-1] - m.S[t-1] + m.S[t]
    )
    m.overtime = pyo.Constraint(T, rule=lambda m, t: m.O[t] <= max_ot * m.W[t])

    # 초기조건
    m.W_0 = pyo.Constraint(rule=lambda m: m.W[0] == w0)
    m.I_0 = pyo.Constraint(rule=lambda m: m.I[0] == i0)
    m.S_0 = pyo.Constraint(rule=lambda m: m.S[0] == 0)

    # 핵심 안정화: 0시점에서 사용하지 않는 변수들도 0으로 고정
    m.H_0 = pyo.Constraint(rule=lambda m: m.H[0] == 0)
    m.L_0 = pyo.Constraint(rule=lambda m: m.L[0] == 0)
    m.P_0 = pyo.Constraint(rule=lambda m: m.P[0] == 0)
    m.C_0 = pyo.Constraint(rule=lambda m: m.C[0] == 0)
    m.O_0 = pyo.Constraint(rule=lambda m: m.O[0] == 0)

    # 최종조건
    m.last_inv = pyo.Constraint(rule=lambda m: m.I[TH] >= i_final)
    m.last_short = pyo.Constraint(rule=lambda m: m.S[TH] == 0)

    # 솔버 실행
    solver_ok = False
    result = None
    last_error = None

    for solver_name in ["appsi_highs", "highs", "glpk"]:
        try:
            solver = pyo.SolverFactory(solver_name)
            result = solver.solve(m)
            solver_ok = True
            break
        except Exception as e:
            last_error = e
            continue

    if not solver_ok or result is None:
        raise RuntimeError(
            f"사용 가능한 솔버가 없습니다. 마지막 오류: {last_error}"
        )

    status = str(result.solver.termination_condition)

    if result.solver.termination_condition not in [TerminationCondition.optimal, TerminationCondition.feasible]:
        raise RuntimeError(
            f"최적해를 찾지 못했습니다. Solver 상태: {status}\n"
            "입력 조건이 너무 제한적일 수 있습니다. 초기 근로자 수, 초기 재고, 초과시간 한도, 최종 목표재고를 조정해 보세요."
        )

    def safe(var, t):
        try:
            v = pyo.value(var[t], exception=False)
            if v is None:
                return 0.0
            # HiGHS/Pyomo 수치오차로 생기는 -0.0, -1e-9 같은 값 제거
            if abs(v) < 1e-6:
                return 0.0
            return max(0.0, float(v))
        except Exception:
            return 0.0

    cost_value = pyo.value(m.Cost, exception=False)
    if cost_value is None:
        raise RuntimeError("최적화 결과 비용을 계산할 수 없습니다. 입력 조건을 다시 확인해 주세요.")
    if abs(cost_value) < 1e-6:
        cost_value = 0.0

    return {
        "status": status,
        "cost": max(0.0, float(cost_value)),
        "W": [safe(m.W, t) for t in TIME],
        "H": [safe(m.H, t) for t in TIME],
        "L": [safe(m.L, t) for t in TIME],
        "P": [safe(m.P, t) for t in TIME],
        "I": [safe(m.I, t) for t in TIME],
        "S": [safe(m.S, t) for t in TIME],
        "C": [safe(m.C, t) for t in TIME],
        "O": [safe(m.O, t) for t in TIME],
    }

# ─────────────────────────────────────────
# 수리모형 설명
# ─────────────────────────────────────────
def show_math_model(prod_pw, reg_cost_pw):
    st.subheader("📐 총괄생산계획 수리모형")

    st.markdown("### 1️⃣ 결정변수")
    st.markdown("""
| 변수 | 설명 | 단위 |
|---|---|---|
| $W_t$ | $t$월의 종업원 수 | 인/월 |
| $H_t$ | $t$월 초에 신규 고용하는 종업원 수 | 인/월 |
| $L_t$ | $t$월 초에 해고하는 종업원 수 | 인/월 |
| $P_t$ | $t$월의 생산량 | 개/월 |
| $I_t$ | $t$월 말의 재고 | 개/월 |
| $S_t$ | $t$월 말의 부족재고 | 개/월 |
| $C_t$ | $t$월의 하청 생산량 | 개/월 |
| $O_t$ | $t$월의 총 초과근무시간 | hr/월 |
    """)

    st.markdown("### 2️⃣ 목적함수")
    st.markdown("총비용을 최소화하는 것을 목표로 한다.")
    st.latex(r"""
    \min Z =
    \sum_{t=1}^{T}
    \left(
    c_r W_t + c_o O_t + c_h H_t + c_f L_t
    + c_i I_t + c_b S_t + c_m P_t + c_s C_t
    \right)
    """)

    st.markdown("### 3️⃣ 제약조건")
    st.markdown("**① 노동력 균형 제약**")
    st.latex(r"W_t = W_{t-1} + H_t - L_t,\quad \forall t")

    st.markdown("**② 생산능력 제약**")
    st.latex(r"P_t \leq \frac{h \cdot d}{\tau} W_t + \frac{O_t}{\tau},\quad \forall t")

    st.markdown("**③ 재고균형 제약**")
    st.latex(r"I_t = I_{t-1} + P_t + C_t - D_t - S_{t-1} + S_t,\quad \forall t")

    st.markdown("**④ 초과근무 제약**")
    st.latex(r"O_t \leq \bar{o} W_t,\quad \forall t")

    st.markdown("**⑤ 초기조건**")
    st.latex(r"W_0 = W_{\mathrm{init}},\quad I_0 = I_{\mathrm{init}},\quad S_0 = 0")

    st.markdown("**⑥ 최종조건**")
    st.latex(r"I_T \geq I_{\mathrm{final}},\quad S_T = 0")

    st.markdown("**⑦ 비음수 제약**")
    st.latex(r"W_t,H_t,L_t,P_t,I_t,S_t,C_t,O_t \geq 0,\quad \forall t")

    if not allow_backorder:
        st.markdown("**⑧ 부족재고 불허 조건**")
        st.latex(r"S_t = 0,\quad \forall t")

    st.markdown("---")
    st.markdown("### 4️⃣ 현재 입력값 기준 주요 파라미터")

    param_df = pd.DataFrame({
        "항목": [
            "1인당 정규 생산능력",
            "1인당 월 정규임금",
            "초과임금",
            "고용비용",
            "해고비용",
            "재고유지비",
            "부재고비용",
            "재료비",
            "하청비용",
            "부족재고 정책",
        ],
        "값": [
            f"{prod_pw:.1f} 개/인/월",
            f"{reg_cost_pw:,.0f} 천원/인/월",
            f"{ot_wage:,.0f} 천원/hr",
            f"{hire_cost:,.0f} 천원/인",
            f"{fire_cost:,.0f} 천원/인",
            f"{hold_cost:,.0f} 천원/개/월",
            f"{back_cost:,.0f} 천원/개/월",
            f"{mat_cost:,.0f} 천원/개",
            f"{sub_cost:,.0f} 천원/개",
            "허용" if allow_backorder else "불허",
        ]
    })

    st.dataframe(param_df, use_container_width=True, hide_index=True)

    with st.expander("📘 APP 구조와 재고균형 메커니즘 이해하기", expanded=False):
        st.markdown("""
**총괄생산계획(APP)**은 중기 수요예측을 바탕으로 생산량, 인력, 재고, 하청, 초과근무를 함께 결정하는 계획입니다.

**계층적 생산계획 구조**
1. 기업 전체 전략 및 수요예측
2. 총괄생산계획(APP)
3. 주생산일정(MPS)
4. 자재소요계획(MRP)
5. 작업장 일정계획

**재고균형 흐름**
전월 재고 + 자체 생산 + 하청 생산 - 당월 수요 - 전월 부족재고 + 당월 부족재고 = 당월 말 재고
""")

    st.info("LP는 모든 변수를 연속변수로 처리하고, IP는 인력 관련 변수 W, H, L을 정수로 제한한다.")

# 현재 입력값 기준 파생값
prod_pw_current = (1 / std_time) * work_hrs * work_days
reg_cost_pw_current = reg_wage * work_hrs * work_days

with st.expander("📐 수리모형 설명 보기", expanded=False):
    show_math_model(prod_pw_current, reg_cost_pw_current)

# ─────────────────────────────────────────
# 실행 버튼
# ─────────────────────────────────────────
col_btn1, col_btn2 = st.columns([1, 3])

with col_btn1:
    run_btn = st.button("🚀 최적화 실행", type="primary", use_container_width=True)

if run_btn:
    with st.spinner("Pyomo로 최적화 계산 중..."):
        try:
            kwargs = dict(
                demands=demands,
                w0=w0,
                i0=i0,
                i_final=i_final,
                reg_wage=reg_wage,
                ot_wage=ot_wage,
                hire_cost=hire_cost,
                fire_cost=fire_cost,
                hold_cost=hold_cost,
                back_cost=back_cost,
                mat_cost=mat_cost,
                sub_cost=sub_cost,
                work_days=work_days,
                work_hrs=work_hrs,
                max_ot=max_ot,
                std_time=std_time,
                allow_backorder=allow_backorder
            )

            res = solve_app(**kwargs, type_mp=type_mp)

            st.session_state["result"] = res
            st.session_state["demands"] = demands.copy()
            st.session_state["type_mp"] = type_mp
            st.session_state["allow_backorder"] = allow_backorder
            st.session_state.pop("scenario_df", None)

            if run_both:
                alt = "IP" if type_mp == "LP" else "LP"
                res2 = solve_app(**kwargs, type_mp=alt)
                st.session_state["result2"] = res2
                st.session_state["type_mp2"] = alt
            else:
                st.session_state.pop("result2", None)
                st.session_state.pop("type_mp2", None)

        except Exception as e:
            st.error(f"❌ 오류 발생:\n\n{e}")

# ─────────────────────────────────────────
# 결과 표시
# ─────────────────────────────────────────
if "result" in st.session_state:
    res = st.session_state["result"]
    demands_used = st.session_state["demands"]
    type_mp_used = st.session_state["type_mp"]
    allow_backorder_used = st.session_state.get("allow_backorder", allow_backorder)

    TH = len(demands_used)
    T_idx = list(range(1, TH + 1))
    mlabels = [f"{t}월" for t in T_idx]
    all_labels = ["초기"] + mlabels

    prod_pw = (1 / std_time) * work_hrs * work_days
    reg_cost_pw = reg_wage * work_hrs * work_days

    def clean_num(x):
        if x is None:
            return 0.0
        if abs(x) < 1e-6:
            return 0.0
        return max(0.0, float(x))

    def cost_breakdown(r):
        return {
            "정규임금": sum(reg_cost_pw * clean_num(r["W"][t]) for t in T_idx),
            "초과임금": sum(ot_wage * clean_num(r["O"][t]) for t in T_idx),
            "고용비용": sum(hire_cost * clean_num(r["H"][t]) for t in T_idx),
            "해고비용": sum(fire_cost * clean_num(r["L"][t]) for t in T_idx),
            "재고유지": sum(hold_cost * clean_num(r["I"][t]) for t in T_idx),
            "부재고": sum(back_cost * clean_num(r["S"][t]) for t in T_idx),
            "재료비": sum(mat_cost * clean_num(r["P"][t]) for t in T_idx),
            "하청비용": sum(sub_cost * clean_num(r["C"][t]) for t in T_idx),
        }

    cb = cost_breakdown(res)
    c_labels = list(cb.keys())
    c_values = list(cb.values())

    ok = "optimal" in res["status"].lower() or "feasible" in res["status"].lower()

    if ok:
        st.success(
            f"✅ 최적해 도출 완료 | 모델: {type_mp_used} | 최소 총비용: **{res['cost']:,.0f} 천원**"
        )
    else:
        st.warning(f"⚠️ 솔버 상태: {res['status']}")

    k1, k2, k3, k4, k5 = st.columns(5)

    kpis = [
        ("총 비용", f"{res['cost']:,.0f} 천원"),
        ("평균 작업자", f"{sum(clean_num(res['W'][t]) for t in T_idx) / TH:.1f} 명"),
        ("총 생산량", f"{sum(clean_num(res['P'][t]) for t in T_idx):,.0f} 개"),
        ("최종 재고", f"{clean_num(res['I'][TH]):,.0f} 개"),
        ("부족재고 정책", "허용" if allow_backorder_used else "불허"),
    ]

    for col, (label, val) in zip([k1, k2, k3, k4, k5], kpis):
        col.markdown(
            f"""
            <div class="kpi-box">
                <div class="kpi-label">{label}</div>
                <div class="kpi-value">{val}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("---")

    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "📋 결과 요약",
        "📊 생산 & 재고",
        "👷 인력 계획",
        "💰 비용 분석",
        "🔄 LP vs IP 비교",
        "⚠️ 실현가능성 점검",
        "🧠 결과 해석",
        "📈 시나리오 분석",
    ])

    with tab1:
        st.subheader("📋 월별 계획 요약 테이블")

        df = pd.DataFrame({
            "월": mlabels,
            "수요(개)": demands_used,
            "작업자(명)": [round(clean_num(res["W"][t]), 1) for t in T_idx],
            "고용(명)": [round(clean_num(res["H"][t]), 1) for t in T_idx],
            "해고(명)": [round(clean_num(res["L"][t]), 1) for t in T_idx],
            "생산량(개)": [round(clean_num(res["P"][t]), 1) for t in T_idx],
            "재고(개)": [round(clean_num(res["I"][t]), 1) for t in T_idx],
            "부족재고(개)": [round(clean_num(res["S"][t]), 1) for t in T_idx],
            "하청(개)": [round(clean_num(res["C"][t]), 1) for t in T_idx],
            "초과시간(hr)": [round(clean_num(res["O"][t]), 1) for t in T_idx],
        })

        def highlight(row):
            s = [""] * len(row)
            if row["부족재고(개)"] > 0:
                s[7] = "background-color:#ffe0e0"
            if row["하청(개)"] > 0:
                s[8] = "background-color:#e0f0ff"
            if row["초과시간(hr)"] > 0:
                s[9] = "background-color:#fff3cd"
            return s

        st.dataframe(df.style.apply(highlight, axis=1), use_container_width=True)
        st.caption("🔴 부족재고  🟡 초과근무  🔵 하청 발생 월")

        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ 결과 CSV 다운로드", csv, "app_result.csv", "text/csv")

    with tab2:
        st.subheader("📊 수요 vs 생산량")

        fig = go.Figure()
        fig.add_trace(go.Bar(x=mlabels, y=demands_used, name="수요", marker_color="#ef553b", opacity=0.75))
        fig.add_trace(go.Bar(x=mlabels, y=[clean_num(res["P"][t]) for t in T_idx], name="자체생산", marker_color="#636efa", opacity=0.85))
        fig.add_trace(go.Bar(x=mlabels, y=[clean_num(res["C"][t]) for t in T_idx], name="하청생산", marker_color="#00cc96", opacity=0.85))
        fig.update_layout(barmode="group", xaxis_title="월", yaxis_title="수량(개)")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("📦 재고 & 부족재고 추이")

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=all_labels,
            y=[clean_num(v) for v in res["I"]],
            mode="lines+markers",
            name="재고",
            line=dict(color="#636efa", width=2),
            fill="tozeroy",
            fillcolor="rgba(99,110,250,0.15)"
        ))
        fig2.add_trace(go.Scatter(
            x=all_labels,
            y=[clean_num(v) for v in res["S"]],
            mode="lines+markers",
            name="부족재고",
            line=dict(color="#ef553b", width=2, dash="dash")
        ))
        fig2.add_hline(
            y=i_final,
            line_dash="dot",
            line_color="green",
            annotation_text=f"목표재고 {i_final}개"
        )
        fig2.update_layout(xaxis_title="시점", yaxis_title="수량(개)")
        st.plotly_chart(fig2, use_container_width=True)

    with tab3:
        st.subheader("👷 월별 인력 현황")

        fig3 = go.Figure()
        fig3.add_trace(go.Bar(x=mlabels, y=[clean_num(res["W"][t]) for t in T_idx], name="총 작업자", marker_color="#ab63fa"))
        fig3.add_trace(go.Scatter(x=mlabels, y=[clean_num(res["H"][t]) for t in T_idx], mode="lines+markers", name="신규고용", line=dict(color="#00cc96", width=2)))
        fig3.add_trace(go.Scatter(x=mlabels, y=[clean_num(res["L"][t]) for t in T_idx], mode="lines+markers", name="해고", line=dict(color="#ef553b", width=2, dash="dash")))
        fig3.update_layout(xaxis_title="월", yaxis_title="인원(명)")
        st.plotly_chart(fig3, use_container_width=True)

        st.subheader("⏱ 월별 초과근무 시간")

        fig4 = go.Figure()
        fig4.add_trace(go.Bar(x=mlabels, y=[clean_num(res["O"][t]) for t in T_idx], marker_color="#ffa15a", name="총 초과시간"))
        fig4.add_trace(go.Scatter(
            x=mlabels,
            y=[max_ot * clean_num(res["W"][t]) for t in T_idx],
            mode="lines",
            name="초과시간 한도",
            line=dict(color="red", dash="dot", width=2)
        ))
        fig4.update_layout(xaxis_title="월", yaxis_title="시간(hr)")
        st.plotly_chart(fig4, use_container_width=True)

    with tab4:
        st.subheader("💰 비용 구성 분석")

        colors = ["#636efa", "#ffa15a", "#00cc96", "#ef553b", "#ab63fa", "#19d3f3", "#ff6692", "#b6e880"]

        col1, col2 = st.columns(2)

        with col1:
            fig5 = go.Figure(go.Pie(
                labels=c_labels,
                values=c_values,
                marker_colors=colors,
                hole=0.4,
                textinfo="label+percent"
            ))
            fig5.update_layout(title="비용 구성 비율")
            st.plotly_chart(fig5, use_container_width=True)

        with col2:
            fig6 = go.Figure(go.Waterfall(
                orientation="v",
                x=c_labels,
                y=c_values,
                increasing={"marker": {"color": "#ef553b"}},
                connector={"line": {"color": "gray"}}
            ))
            fig6.update_layout(title="비용 항목별 기여도", yaxis_title="천원")
            st.plotly_chart(fig6, use_container_width=True)

        st.subheader("📉 월별 비용 추이")

        monthly = [
            reg_cost_pw * clean_num(res["W"][t])
            + ot_wage * clean_num(res["O"][t])
            + hire_cost * clean_num(res["H"][t])
            + fire_cost * clean_num(res["L"][t])
            + hold_cost * clean_num(res["I"][t])
            + back_cost * clean_num(res["S"][t])
            + mat_cost * clean_num(res["P"][t])
            + sub_cost * clean_num(res["C"][t])
            for t in T_idx
        ]

        fig7 = go.Figure()
        fig7.add_trace(go.Bar(x=mlabels, y=monthly, marker_color="#636efa", name="월별 비용"))
        fig7.add_trace(go.Scatter(x=mlabels, y=monthly, mode="lines+markers", name="추이", line=dict(color="#ef553b", width=2)))
        fig7.update_layout(xaxis_title="월", yaxis_title="비용(천원)")
        st.plotly_chart(fig7, use_container_width=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("총 비용", f"{res['cost']:,.0f} 천원")
        m2.metric("재료비 비중", f"{cb['재료비'] / res['cost'] * 100:.1f}%")
        m3.metric("인건비 비중", f"{(cb['정규임금'] + cb['초과임금']) / res['cost'] * 100:.1f}%")
        m4.metric("재고 관련 비중", f"{(cb['재고유지'] + cb['부재고']) / res['cost'] * 100:.1f}%")

    with tab5:
        st.subheader("🔄 LP vs IP 시나리오 비교")

        if "result2" in st.session_state:
            res2 = st.session_state["result2"]
            type2 = st.session_state["type_mp2"]
            cb2 = cost_breakdown(res2)

            c1, c2 = st.columns(2)

            with c1:
                st.markdown(f"### {type_mp_used} 결과")
                st.metric("최소 총비용", f"{res['cost']:,.0f} 천원")
                st.metric("평균 작업자", f"{sum(clean_num(res['W'][t]) for t in T_idx) / TH:.1f} 명")
                st.metric("총 생산량", f"{sum(clean_num(res['P'][t]) for t in T_idx):,.0f} 개")

            with c2:
                diff = res2["cost"] - res["cost"]
                st.markdown(f"### {type2} 결과")
                st.metric("최소 총비용", f"{res2['cost']:,.0f} 천원", delta=f"{diff:+,.0f} 천원")
                st.metric("평균 작업자", f"{sum(clean_num(res2['W'][t]) for t in T_idx) / TH:.1f} 명")
                st.metric("총 생산량", f"{sum(clean_num(res2['P'][t]) for t in T_idx):,.0f} 개")

            fig_cmp = go.Figure()
            fig_cmp.add_trace(go.Bar(name=type_mp_used, x=list(cb.keys()), y=list(cb.values()), marker_color="#636efa"))
            fig_cmp.add_trace(go.Bar(name=type2, x=list(cb2.keys()), y=list(cb2.values()), marker_color="#ef553b", opacity=0.8))
            fig_cmp.update_layout(barmode="group", title="비용 항목 비교", xaxis_title="비용 항목", yaxis_title="천원")
            st.plotly_chart(fig_cmp, use_container_width=True)

        else:
            st.info("👈 사이드바에서 **LP & IP 동시 비교**를 체크한 뒤 최적화 실행을 눌러주세요.")

    with tab6:
        st.subheader("⚠️ 계획 실현가능성 점검")

        checks = []

        shortage = [mlabels[i] for i, t in enumerate(T_idx) if clean_num(res["S"][t]) > 0.01]
        if shortage:
            checks.append(("bad", "부족재고 발생", f"발생 월: {', '.join(shortage)} — 납기 지연 위험"))
        else:
            checks.append(("ok", "부족재고 없음", "전 기간 수요 충족 ✅"))

        ot_near = [
            mlabels[i]
            for i, t in enumerate(T_idx)
            if clean_num(res["O"][t]) > max_ot * clean_num(res["W"][t]) * 0.9 and clean_num(res["O"][t]) > 0.01
        ]
        if ot_near:
            checks.append(("warn", "초과근무 한도 근접", f"주의 필요 월: {', '.join(ot_near)}"))
        else:
            checks.append(("ok", "초과근무 정상 범위", "초과시간 한도 여유 있음 ✅"))

        if clean_num(res["I"][TH]) >= i_final:
            checks.append(("ok", "최종재고 목표 달성", f"최종재고: {clean_num(res['I'][TH]):.0f}개 / 목표: {i_final}개 ✅"))
        else:
            checks.append(("bad", "최종재고 목표 미달", f"최종재고: {clean_num(res['I'][TH]):.0f}개 / 목표: {i_final}개"))

        hire_m = [mlabels[i] for i, t in enumerate(T_idx) if clean_num(res["H"][t]) > 0.01]
        fire_m = [mlabels[i] for i, t in enumerate(T_idx) if clean_num(res["L"][t]) > 0.01]
        sub_m = [mlabels[i] for i, t in enumerate(T_idx) if clean_num(res["C"][t]) > 0.01]

        if hire_m:
            checks.append(("warn", "신규 고용 발생", f"고용 월: {', '.join(hire_m)}"))
        if fire_m:
            checks.append(("warn", "해고 발생", f"해고 월: {', '.join(fire_m)}"))
        if sub_m:
            checks.append(("warn", "하청 발생", f"하청 월: {', '.join(sub_m)}"))
        else:
            checks.append(("ok", "하청 없음", "자체 생산으로 수요 충족 ✅"))

        css_map = {"ok": "status-ok", "warn": "status-warn", "bad": "status-bad"}

        for level, title, desc in checks:
            icon = "🟢" if level == "ok" else ("🟡" if level == "warn" else "🔴")
            st.markdown(
                f'<div class="{css_map[level]}"><strong>{icon} {title}</strong><br>{desc}</div>',
                unsafe_allow_html=True
            )

        red = sum(1 for c in checks if c[0] == "bad")

        st.markdown("---")
        if red == 0:
            st.success("✅ 종합 판정: 계획이 실현가능하며 안정적입니다.")
        elif red == 1:
            st.warning("⚠️ 종합 판정: 일부 항목을 검토할 필요가 있습니다.")
        else:
            st.error("❌ 종합 판정: 계획 재수립을 권장합니다.")

    with tab7:
        st.subheader("🧠 최적화 결과 해석")

        total_demand = sum(demands_used)
        total_prod = sum(clean_num(res["P"][t]) for t in T_idx)
        total_sub = sum(clean_num(res["C"][t]) for t in T_idx)
        total_ot = sum(clean_num(res["O"][t]) for t in T_idx)
        total_hire = sum(clean_num(res["H"][t]) for t in T_idx)
        total_fire = sum(clean_num(res["L"][t]) for t in T_idx)
        avg_worker = sum(clean_num(res["W"][t]) for t in T_idx) / TH
        max_short = max(clean_num(res["S"][t]) for t in T_idx)
        max_inv = max(clean_num(res["I"][t]) for t in T_idx)

        st.markdown(f"""
        ### 📌 종합 해석
        본 모형은 총 **{TH}개월** 동안의 예상 수요를 충족하면서 총비용을 최소화하는 총괄생산계획을 도출하였다.

        - 선택 모형: **{type_mp_used}**
        - 최소 총비용: **{res['cost']:,.0f}천원**
        - 총수요: **{total_demand:,.0f}개**
        - 자체 생산량: **{total_prod:,.0f}개**
        - 하청 생산량: **{total_sub:,.0f}개**
        - 평균 작업자 수: **{avg_worker:.1f}명**
        - 최대 재고: **{max_inv:,.0f}개**
        - 최대 부족재고: **{max_short:,.0f}개**
        """)

        if total_sub > 0:
            st.warning(
                f"하청 생산이 총 {total_sub:,.0f}개 발생하였다. 이는 자체 생산능력만으로 수요를 충족하기보다 외주를 활용하는 것이 비용 측면에서 유리하다는 의미이다."
            )
        else:
            st.success("하청 없이 자체 생산만으로 수요를 충족하였다.")

        if total_ot > 0:
            st.warning(
                f"초과근무가 총 {total_ot:,.0f}시간 발생하였다. 이는 특정 월의 생산능력 부족을 초과근무로 보완한 결과로 해석할 수 있다."
            )
        else:
            st.success("초과근무 없이 정규 생산능력만으로 계획이 수립되었다.")

        if total_hire > 0 or total_fire > 0:
            st.info(
                f"계획기간 중 신규고용은 {total_hire:,.0f}명, 해고는 {total_fire:,.0f}명 발생하였다. 수요 변동에 대응하기 위해 인력 수준을 조정한 결과이다."
            )
        else:
            st.success("고용 및 해고 없이 기존 인력 수준으로 운영 가능한 계획이다.")

        if max_short > 0:
            st.error(
                f"최대 부족재고가 {max_short:,.0f}개 발생하였다. 납기 지연 가능성이 있으므로 조건을 재검토할 필요가 있다."
            )
        else:
            st.success("부족재고가 발생하지 않아 모든 월의 수요를 충족하는 계획이다.")

        st.markdown("---")
        st.subheader("📋 제약조건 검증표")
        validation_rows = []

        for t in T_idx:
            labor_rhs = clean_num(res["W"][t - 1]) + clean_num(res["H"][t]) - clean_num(res["L"][t])
            cap_rhs = prod_pw * clean_num(res["W"][t]) + clean_num(res["O"][t]) / std_time
            inv_rhs = clean_num(res["I"][t - 1]) + clean_num(res["P"][t]) + clean_num(res["C"][t]) - demands_used[t - 1] - clean_num(res["S"][t - 1]) + clean_num(res["S"][t])
            ot_rhs = max_ot * clean_num(res["W"][t])

            validation_rows.append({
                "월": f"{t}월",
                "노동력 제약 오차": round(abs(clean_num(res["W"][t]) - labor_rhs), 6),
                "생산능력 여유": round(cap_rhs - clean_num(res["P"][t]), 3),
                "재고균형 오차": round(abs(clean_num(res["I"][t]) - inv_rhs), 6),
                "초과근무 여유": round(ot_rhs - clean_num(res["O"][t]), 3),
            })

        valid_df = pd.DataFrame(validation_rows)
        st.dataframe(valid_df, use_container_width=True, hide_index=True)

        if (
            valid_df["노동력 제약 오차"].max() < 1e-4
            and valid_df["재고균형 오차"].max() < 1e-4
            and valid_df["생산능력 여유"].min() >= -1e-4
            and valid_df["초과근무 여유"].min() >= -1e-4
        ):
            st.success("✅ 모든 주요 제약조건이 정상적으로 만족되었습니다.")
        else:
            st.error("❌ 일부 제약조건에서 위반 가능성이 있습니다.")

    with tab8:
        st.subheader("📈 수요 변화 시나리오 분석")
        st.markdown("민감도 분석은 계산량이 많기 때문에 버튼을 눌렀을 때만 실행됩니다.")

        run_scenario = st.button("📈 민감도 분석 실행", use_container_width=True)

        if run_scenario:
            scenario_rates = [-0.2, -0.1, 0, 0.1, 0.2]
            scenario_results = []
            base_kwargs = dict(
                w0=w0,
                i0=i0,
                i_final=i_final,
                reg_wage=reg_wage,
                ot_wage=ot_wage,
                hire_cost=hire_cost,
                fire_cost=fire_cost,
                hold_cost=hold_cost,
                back_cost=back_cost,
                mat_cost=mat_cost,
                sub_cost=sub_cost,
                work_days=work_days,
                work_hrs=work_hrs,
                max_ot=max_ot,
                std_time=std_time,
                allow_backorder=allow_backorder_used,
            )

            with st.spinner("수요 변화 시나리오 분석 중..."):
                for rate in scenario_rates:
                    try:
                        scenario_demand = [round(d * (1 + rate)) for d in demands_used]
                        scenario_res = solve_app(demands=scenario_demand, type_mp=type_mp_used, **base_kwargs)
                        scenario_results.append({
                            "시나리오": f"{int(rate * 100):+d}%",
                            "변화율": rate,
                            "총수요": sum(scenario_demand),
                            "총비용(천원)": round(scenario_res["cost"], 0),
                            "총 생산량": round(sum(clean_num(scenario_res["P"][t]) for t in T_idx), 0),
                            "총 하청량": round(sum(clean_num(scenario_res["C"][t]) for t in T_idx), 0),
                            "총 초과시간": round(sum(clean_num(scenario_res["O"][t]) for t in T_idx), 0),
                            "평균 작업자": round(sum(clean_num(scenario_res["W"][t]) for t in T_idx) / TH, 1),
                            "상태": scenario_res["status"],
                        })
                    except Exception as e:
                        scenario_results.append({
                            "시나리오": f"{int(rate * 100):+d}%",
                            "변화율": rate,
                            "총수요": None,
                            "총비용(천원)": None,
                            "총 생산량": None,
                            "총 하청량": None,
                            "총 초과시간": None,
                            "평균 작업자": None,
                            "상태": f"실패: {e}",
                        })

            st.session_state["scenario_df"] = pd.DataFrame(scenario_results)

        if "scenario_df" in st.session_state:
            scenario_df = st.session_state["scenario_df"]
            st.dataframe(scenario_df.drop(columns=["변화율"]), use_container_width=True, hide_index=True)
            plot_df = scenario_df.dropna(subset=["총비용(천원)"]).copy()

            if len(plot_df) > 0:
                fig_s1 = go.Figure()
                fig_s1.add_trace(go.Bar(
                    x=plot_df["시나리오"],
                    y=plot_df["총비용(천원)"],
                    marker_color="#636efa",
                    name="총비용"
                ))
                fig_s1.update_layout(
                    title="수요 변화에 따른 총비용 변화",
                    xaxis_title="수요 변화율",
                    yaxis_title="총비용(천원)"
                )
                st.plotly_chart(fig_s1, use_container_width=True)

                fig_s2 = go.Figure()
                fig_s2.add_trace(go.Scatter(
                    x=plot_df["시나리오"],
                    y=plot_df["총 생산량"],
                    mode="lines+markers",
                    name="총 생산량",
                    line=dict(color="#636efa", width=2)
                ))
                fig_s2.add_trace(go.Scatter(
                    x=plot_df["시나리오"],
                    y=plot_df["총 하청량"],
                    mode="lines+markers",
                    name="총 하청량",
                    line=dict(color="#ef553b", width=2, dash="dash")
                ))
                fig_s2.update_layout(
                    title="수요 변화에 따른 생산 및 하청 변화",
                    xaxis_title="수요 변화율",
                    yaxis_title="수량(개)"
                )
                st.plotly_chart(fig_s2, use_container_width=True)

                base_row = plot_df[plot_df["변화율"] == 0]
                high_row = plot_df[plot_df["변화율"] == 0.2]
                low_row = plot_df[plot_df["변화율"] == -0.2]

                if not base_row.empty and not high_row.empty and not low_row.empty:
                    base_cost = float(base_row["총비용(천원)"].iloc[0])
                    high_cost = float(high_row["총비용(천원)"].iloc[0])
                    low_cost = float(low_row["총비용(천원)"].iloc[0])
                    st.info(
                        f"현재 기준 대비 수요가 20% 증가하면 총비용은 약 {high_cost - base_cost:,.0f}천원 증가하고, "
                        f"수요가 20% 감소하면 총비용은 약 {base_cost - low_cost:,.0f}천원 감소합니다."
                    )
        else:
            st.info("최적화 결과를 확인한 뒤 필요할 때 민감도 분석 실행 버튼을 눌러주세요.")

else:
    st.info("👈 왼쪽 사이드바에서 파라미터를 설정하고 **🚀 최적화 실행** 버튼을 눌러주세요!")
    st.markdown("""
    ### 📖 앱 사용 방법
    1. **사이드바**에서 수요, 인력, 재고, 생산 파라미터를 설정합니다.
    2. **LP / IP** 중 최적화 방법을 선택합니다.
    3. 위의 **📐 수리모형 설명 보기**에서 모형 구조를 확인할 수 있습니다.
    4. **🚀 최적화 실행** 버튼을 클릭합니다.
    5. 결과 탭에서 최적 생산계획을 확인합니다.

    #### 제공 기능
    - 📐 최적화 전 수리모형 설명
    - 📋 월별 결과 요약표
    - 📊 생산 및 재고 그래프
    - 👷 인력 계획 분석
    - 💰 비용 구성 분석
    - 🔄 LP vs IP 비교
    - ⚠️ 실현가능성 점검
    - 🧠 자동 결과 해석
    - 📈 수요 변화 시나리오 분석
    """)
