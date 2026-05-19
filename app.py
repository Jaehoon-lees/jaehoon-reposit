import streamlit as st
import requests
import json
import os
from dataclasses import dataclass
from typing import Optional

ZOOMINFO_BASE_URL = "https://api.zoominfo.com"

STAFFBASE_ICP_TITLES = [
    "Internal Communications",
    "Employee Communications",
    "Employee Experience",
    "Corporate Communications",
    "People & Culture",
    "HR Communications",
    "Workplace Experience",
    "Internal Comms",
    "People Communications",
    "Change Communications",
]

STAFFBASE_ICP_LEVELS = [
    "C-Level",
    "VP",
    "Director",
    "Manager",
]


@dataclass
class ZoomInfoClient:
    username: str
    password: str
    _token: Optional[str] = None

    def authenticate(self) -> bool:
        resp = requests.post(
            f"{ZOOMINFO_BASE_URL}/authenticate",
            json={"username": self.username, "password": self.password},
        )
        if resp.status_code == 200:
            self._token = resp.json().get("jwt")
            return True
        return False

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def search_company(self, company_name: str) -> dict:
        payload = {
            "outputFields": ["id", "name", "website", "revenue", "employeeCount", "industry"],
            "matchCompanyInput": [{"name": company_name}],
        }
        resp = requests.post(
            f"{ZOOMINFO_BASE_URL}/enrich/company",
            headers=self.headers,
            json=payload,
        )
        return resp.json() if resp.status_code == 200 else {}

    def search_icp_contacts(self, company_name: str, company_id: Optional[int] = None) -> list:
        match_company = {"companyId": company_id} if company_id else {"name": company_name}

        payload = {
            "outputFields": [
                "id", "firstName", "lastName", "jobTitle",
                "managementLevel", "email", "phone",
                "companyName", "linkedInUrl",
            ],
            "personCriteria": {
                "jobTitle": STAFFBASE_ICP_TITLES,
            },
            "companyList": [match_company],
        }
        resp = requests.post(
            f"{ZOOMINFO_BASE_URL}/search/contact",
            headers=self.headers,
            json=payload,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        contacts = data.get("data", {}).get("outputFields", [])
        return _filter_by_level(contacts)


def _filter_by_level(contacts: list) -> list:
    filtered = []
    for c in contacts:
        level = c.get("managementLevel", "")
        if any(lvl.lower() in level.lower() for lvl in STAFFBASE_ICP_LEVELS):
            filtered.append(c)
    return filtered if filtered else contacts


def _score_contact(contact: dict) -> int:
    """Score contact relevance to Staffbase ICP (higher = better fit)."""
    score = 0
    title = (contact.get("jobTitle") or "").lower()
    level = (contact.get("managementLevel") or "").lower()

    priority_keywords = ["internal communications", "employee communications", "employee experience"]
    secondary_keywords = ["corporate communications", "people & culture", "hr communications"]

    if any(kw in title for kw in priority_keywords):
        score += 3
    elif any(kw in title for kw in secondary_keywords):
        score += 2

    if "c-level" in level or "vp" in level:
        score += 2
    elif "director" in level:
        score += 1

    if contact.get("email"):
        score += 1

    return score


# ── Streamlit UI ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Staffbase ICP Finder",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 Staffbase ICP Finder")
st.caption("기업명을 입력하면 Staffbase와 연관된 핵심 의사결정자(ICP)를 찾아드립니다.")

with st.sidebar:
    st.header("🔑 ZoomInfo 인증")
    st.caption("ZoomInfo 계정 정보를 입력하세요.")
    username = st.text_input("이메일", value=os.getenv("ZOOMINFO_USERNAME", ""))
    password = st.text_input("비밀번호", type="password", value=os.getenv("ZOOMINFO_PASSWORD", ""))

    st.divider()
    st.header("🎯 ICP 필터 설정")
    st.caption("검색할 직책 키워드")
    selected_titles = st.multiselect(
        "직책 키워드",
        options=STAFFBASE_ICP_TITLES,
        default=STAFFBASE_ICP_TITLES,
    )
    st.caption("검색할 직급")
    selected_levels = st.multiselect(
        "직급",
        options=STAFFBASE_ICP_LEVELS,
        default=STAFFBASE_ICP_LEVELS,
    )

    st.divider()
    st.markdown(
        """
        **Staffbase ICP란?**

        Staffbase는 직원 커뮤니케이션 플랫폼으로,
        주요 구매 의사결정자는 다음과 같습니다:
        - 내부 커뮤니케이션 담당자
        - Employee Experience 담당자
        - Corporate Communications 담당자
        - HR 리더십
        """
    )

col1, col2 = st.columns([3, 1])
with col1:
    company_input = st.text_input(
        "기업명 검색",
        placeholder="예: Deutsche Telekom, Siemens, Bosch...",
        label_visibility="collapsed",
    )
with col2:
    search_btn = st.button("검색", type="primary", use_container_width=True)

if search_btn and company_input:
    if not username or not password:
        st.error("사이드바에서 ZoomInfo 계정 정보를 입력해주세요.")
        st.stop()

    client = ZoomInfoClient(username=username, password=password)

    with st.spinner("ZoomInfo 인증 중..."):
        auth_ok = client.authenticate()

    if not auth_ok:
        st.error("ZoomInfo 인증에 실패했습니다. 계정 정보를 확인해주세요.")
        st.stop()

    company_id = None
    company_info = {}

    with st.spinner(f"'{company_input}' 기업 정보 조회 중..."):
        company_data = client.search_company(company_input)
        results = company_data.get("data", [])
        if results:
            company_info = results[0] if isinstance(results, list) else results
            company_id = company_info.get("id")

    if company_info:
        st.subheader(f"🏢 {company_info.get('name', company_input)}")
        meta_cols = st.columns(3)
        with meta_cols[0]:
            st.metric("직원 수", f"{company_info.get('employeeCount', 'N/A'):,}" if isinstance(company_info.get('employeeCount'), int) else "N/A")
        with meta_cols[1]:
            st.metric("업종", company_info.get("industry", "N/A"))
        with meta_cols[2]:
            website = company_info.get("website", "")
            st.metric("웹사이트", website or "N/A")
    else:
        st.info(f"'{company_input}'의 기업 정보를 찾지 못했습니다. 연락처 검색을 계속합니다.")

    with st.spinner("ICP 의사결정자 검색 중..."):
        contacts = client.search_icp_contacts(company_input, company_id)

    if not contacts:
        st.warning("해당 기업에서 Staffbase ICP 조건에 맞는 담당자를 찾지 못했습니다.")
    else:
        scored = sorted(contacts, key=_score_contact, reverse=True)

        st.subheader(f"👥 ICP 의사결정자 {len(scored)}명 발견")

        for i, contact in enumerate(scored):
            relevance = _score_contact(contact)
            badge = "🔥 최우선" if relevance >= 5 else "✅ 적합" if relevance >= 3 else "📋 참고"

            with st.expander(
                f"{badge} | {contact.get('firstName', '')} {contact.get('lastName', '')} — {contact.get('jobTitle', 'N/A')}",
                expanded=(i < 3),
            ):
                info_cols = st.columns(2)
                with info_cols[0]:
                    st.markdown(f"**직책:** {contact.get('jobTitle', 'N/A')}")
                    st.markdown(f"**직급:** {contact.get('managementLevel', 'N/A')}")
                    st.markdown(f"**회사:** {contact.get('companyName', 'N/A')}")
                with info_cols[1]:
                    email = contact.get("email", "")
                    phone = contact.get("phone", "")
                    linkedin = contact.get("linkedInUrl", "")
                    st.markdown(f"**이메일:** {email if email else '비공개'}")
                    st.markdown(f"**전화:** {phone if phone else '비공개'}")
                    if linkedin:
                        st.markdown(f"**LinkedIn:** [프로필 보기]({linkedin})")

        st.divider()
        st.caption(f"총 {len(scored)}명 | 관련도 순으로 정렬됨")

elif search_btn and not company_input:
    st.warning("기업명을 입력해주세요.")
