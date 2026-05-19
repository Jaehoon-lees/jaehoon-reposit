import streamlit as st
import requests
import os
import re
from dataclasses import dataclass, field
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

ZOOMINFO_BASE_URL = "https://api.zoominfo.com"
SERPER_URL = "https://google.serper.dev/search"

STAFFBASE_ICP_TITLES_EN = [
    "Internal Communications",
    "Employee Communications",
    "Employee Experience",
    "Corporate Communications",
    "People & Culture",
    "HR Communications",
    "Workplace Experience",
    "Change Communications",
]

STAFFBASE_ICP_TITLES_JP = [
    "社内広報",
    "インターナルコミュニケーション",
    "従業員エクスペリエンス",
    "広報部長",
    "人事部長",
    "コーポレートコミュニケーション",
    "社員コミュニケーション",
]

ICP_LEVELS = ["C-Level", "VP", "Director", "Manager", "部長", "執行役員", "取締役"]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Contact:
    name: str
    title: str
    company: str
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    source: str = ""
    source_url: str = ""
    snippet: str = ""
    score: int = 0


# ── ZoomInfo ──────────────────────────────────────────────────────────────────

class ZoomInfoClient:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self._token: Optional[str] = None

    def authenticate(self) -> bool:
        resp = requests.post(
            f"{ZOOMINFO_BASE_URL}/authenticate",
            json={"username": self.username, "password": self.password},
            timeout=10,
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
            "outputFields": ["id", "name", "website", "employeeCount", "industry"],
            "matchCompanyInput": [{"name": company_name}],
        }
        try:
            resp = requests.post(f"{ZOOMINFO_BASE_URL}/enrich/company", headers=self.headers, json=payload, timeout=10)
            return resp.json() if resp.status_code == 200 else {}
        except Exception:
            return {}

    def search_icp_contacts(self, company_name: str, company_id: Optional[int] = None) -> list[Contact]:
        match_company = {"companyId": company_id} if company_id else {"name": company_name}
        payload = {
            "outputFields": ["id", "firstName", "lastName", "jobTitle", "managementLevel", "email", "phone", "companyName", "linkedInUrl"],
            "personCriteria": {"jobTitle": STAFFBASE_ICP_TITLES_EN},
            "companyList": [match_company],
        }
        try:
            resp = requests.post(f"{ZOOMINFO_BASE_URL}/search/contact", headers=self.headers, json=payload, timeout=10)
            if resp.status_code != 200:
                return []
            raw = resp.json().get("data", {}).get("outputFields", [])
            contacts = []
            for c in raw:
                contacts.append(Contact(
                    name=f"{c.get('firstName', '')} {c.get('lastName', '')}".strip(),
                    title=c.get("jobTitle", ""),
                    company=c.get("companyName", company_name),
                    email=c.get("email", ""),
                    phone=c.get("phone", ""),
                    linkedin=c.get("linkedInUrl", ""),
                    source="ZoomInfo",
                ))
            return contacts
        except Exception:
            return []


# ── Google / Nikkei via Serper ─────────────────────────────────────────────────

class SerperClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _search(self, query: str, num: int = 10) -> list[dict]:
        try:
            resp = requests.post(
                SERPER_URL,
                headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                json={"q": query, "num": num},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("organic", [])
        except Exception:
            pass
        return []

    def google_search(self, company_name: str) -> list[Contact]:
        titles_query = " OR ".join(f'"{t}"' for t in STAFFBASE_ICP_TITLES_EN[:5])
        query = f'"{company_name}" ({titles_query}) Director OR VP OR Manager'
        results = self._search(query)
        return self._parse_results(results, company_name, source="Google")

    def nikkei_search(self, company_name: str) -> list[Contact]:
        jp_query = " OR ".join(STAFFBASE_ICP_TITLES_JP[:4])
        query = f'site:nikkei.com "{company_name}" ({jp_query} OR 広報 OR 人事)'
        results = self._search(query)
        return self._parse_results(results, company_name, source="日経新聞")

    def news_search(self, company_name: str) -> list[Contact]:
        query = f'"{company_name}" "internal communications" OR "employee experience" OR "corporate communications" -site:linkedin.com'
        results = self._search(query)
        return self._parse_results(results, company_name, source="ニュース")

    def _parse_results(self, results: list[dict], company_name: str, source: str) -> list[Contact]:
        contacts = []
        name_patterns = [
            r'\b([A-Z][a-z]+ [A-Z][a-z]+)\b',
            r'([一-龯々ぁ-ん]{2,4})\s*(?:部長|執行役員|取締役|マネージャー|ディレクター)',
        ]
        title_keywords = STAFFBASE_ICP_TITLES_EN + STAFFBASE_ICP_TITLES_JP + ["広報", "人事", "コミュニケーション"]

        for r in results:
            snippet = r.get("snippet", "")
            title_text = r.get("title", "")
            url = r.get("link", "")
            combined = f"{title_text} {snippet}"

            matched_title = next((kw for kw in title_keywords if kw.lower() in combined.lower()), "")
            if not matched_title:
                continue

            for pattern in name_patterns:
                for match in re.findall(pattern, combined):
                    name = match if isinstance(match, str) else match[0]
                    if name and name not in [c.name for c in contacts]:
                        contacts.append(Contact(
                            name=name,
                            title=matched_title,
                            company=company_name,
                            source=source,
                            source_url=url,
                            snippet=snippet[:200],
                        ))
        return contacts


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_contact(contact: Contact) -> int:
    score = 0
    title = (contact.title or "").lower()

    priority = ["internal communications", "employee communications", "employee experience", "社内広報"]
    secondary = ["corporate communications", "people & culture", "hr communications", "広報"]

    if any(kw in title for kw in priority):
        score += 3
    elif any(kw in title for kw in secondary):
        score += 2

    if contact.email:
        score += 2
    if contact.linkedin:
        score += 1
    if contact.source == "ZoomInfo":
        score += 2
    if contact.source == "日経新聞":
        score += 1

    return score


def deduplicate(contacts: list[Contact]) -> list[Contact]:
    seen = set()
    result = []
    for c in contacts:
        key = c.name.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(c)
    return result


# ── Streamlit UI ──────────────────────────────────────────────────────────────

st.set_page_config(page_title="Staffbase ICP Finder", page_icon="🎯", layout="wide")

st.title("🎯 Staffbase ICP Finder")
st.caption("기업명을 입력하면 Google, 닛케이, ZoomInfo 등 여러 소스에서 Staffbase ICP 의사결정자를 찾아드립니다.")

with st.sidebar:
    st.header("🔑 API 키 설정")

    st.subheader("Serper.dev (Google 검색)")
    st.caption("무료 가입 → serper.dev 에서 API 키 발급")
    serper_key = st.text_input("Serper API Key", type="password", value=os.getenv("SERPER_API_KEY", ""))

    st.divider()
    st.subheader("ZoomInfo (선택)")
    st.caption("ZoomInfo 계정이 있을 때만 입력하세요")
    zi_username = st.text_input("이메일", value=os.getenv("ZOOMINFO_USERNAME", ""))
    zi_password = st.text_input("비밀번호", type="password", value=os.getenv("ZOOMINFO_PASSWORD", ""))

    st.divider()
    st.subheader("검색 소스 선택")
    use_google = st.checkbox("Google 일반 검색", value=True)
    use_nikkei = st.checkbox("닛케이 신문 (nikkei.com)", value=True)
    use_news = st.checkbox("뉴스 기사 전체", value=True)
    use_zoominfo = st.checkbox("ZoomInfo DB", value=bool(zi_username))

    st.divider()
    st.markdown("""
    **API 키 발급 방법**
    - **Serper.dev**: [serper.dev](https://serper.dev) 가입 → Dashboard → API Key 복사 (월 2,500건 무료)
    - **ZoomInfo**: 기존 계정 그대로 사용
    """)

col1, col2 = st.columns([3, 1])
with col1:
    company_input = st.text_input("기업명", placeholder="예: Siemens, Toyota, Bosch, NTT...", label_visibility="collapsed")
with col2:
    search_btn = st.button("검색", type="primary", use_container_width=True)

if search_btn and company_input:
    if not serper_key and not (zi_username and zi_password):
        st.error("최소 하나의 API 키(Serper 또는 ZoomInfo)가 필요합니다.")
        st.stop()

    all_contacts: list[Contact] = []
    source_status = {}

    if serper_key:
        serper = SerperClient(serper_key)

        if use_google:
            with st.spinner("Google 검색 중..."):
                results = serper.google_search(company_input)
                all_contacts.extend(results)
                source_status["Google"] = len(results)

        if use_nikkei:
            with st.spinner("닛케이 신문 검색 중..."):
                results = serper.nikkei_search(company_input)
                all_contacts.extend(results)
                source_status["日経新聞"] = len(results)

        if use_news:
            with st.spinner("뉴스 기사 검색 중..."):
                results = serper.news_search(company_input)
                all_contacts.extend(results)
                source_status["ニュース"] = len(results)

    if use_zoominfo and zi_username and zi_password:
        with st.spinner("ZoomInfo 인증 및 검색 중..."):
            zi = ZoomInfoClient(zi_username, zi_password)
            if zi.authenticate():
                company_data = zi.search_company(company_input)
                company_results = company_data.get("data", [])
                company_id = None
                if company_results:
                    info = company_results[0] if isinstance(company_results, list) else company_results
                    company_id = info.get("id")
                    st.subheader(f"🏢 {info.get('name', company_input)}")
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        emp = info.get("employeeCount")
                        st.metric("직원 수", f"{emp:,}" if isinstance(emp, int) else "N/A")
                    with c2:
                        st.metric("업종", info.get("industry", "N/A"))
                    with c3:
                        st.metric("웹사이트", info.get("website", "N/A"))

                zi_contacts = zi.search_icp_contacts(company_input, company_id)
                all_contacts.extend(zi_contacts)
                source_status["ZoomInfo"] = len(zi_contacts)
            else:
                st.warning("ZoomInfo 인증 실패. 다른 소스 결과만 표시합니다.")

    # 소스별 요약
    if source_status:
        st.markdown("**검색 결과 요약**")
        cols = st.columns(len(source_status))
        for i, (src, cnt) in enumerate(source_status.items()):
            with cols[i]:
                st.metric(src, f"{cnt}명 발견")

    # 중복 제거 + 스코어링
    unique_contacts = deduplicate(all_contacts)
    scored = sorted(unique_contacts, key=score_contact, reverse=True)

    if not scored:
        st.warning(f"'{company_input}'에서 Staffbase ICP 조건에 맞는 담당자를 찾지 못했습니다.")
        st.info("검색 팁: 회사 영문명 또는 일본어 정식 명칭으로 다시 시도해보세요.")
    else:
        st.subheader(f"👥 ICP 의사결정자 {len(scored)}명 발견")

        for i, contact in enumerate(scored):
            s = score_contact(contact)
            badge = "🔥 최우선" if s >= 5 else "✅ 적합" if s >= 3 else "📋 참고"
            source_tag = f"[{contact.source}]"

            with st.expander(
                f"{badge} {source_tag} | {contact.name} — {contact.title}",
                expanded=(i < 3),
            ):
                left, right = st.columns(2)
                with left:
                    st.markdown(f"**이름:** {contact.name}")
                    st.markdown(f"**직책:** {contact.title}")
                    st.markdown(f"**회사:** {contact.company}")
                    st.markdown(f"**출처:** {contact.source}")
                with right:
                    if contact.email:
                        st.markdown(f"**이메일:** {contact.email}")
                    if contact.phone:
                        st.markdown(f"**전화:** {contact.phone}")
                    if contact.linkedin:
                        st.markdown(f"**LinkedIn:** [프로필 보기]({contact.linkedin})")
                    if contact.source_url:
                        st.markdown(f"**기사/링크:** [보기]({contact.source_url})")

                if contact.snippet:
                    st.caption(f"📄 {contact.snippet}")

        st.divider()
        st.caption(f"총 {len(scored)}명 | 관련도 순 정렬 | 중복 제거 완료")

elif search_btn and not company_input:
    st.warning("기업명을 입력해주세요.")
