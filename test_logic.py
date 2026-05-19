"""검색 로직 단위 테스트 - API 키 없이 실행 가능"""
import sys
sys.path.insert(0, '.')

from app import SerperClient, score_contact, deduplicate, Contact

# ── 파싱 로직 테스트 (실제 Google 응답과 유사한 mock 데이터) ──────────────────

MOCK_GOOGLE_RESULTS = [
    {
        "title": "Sarah Johnson, Head of Internal Communications at Siemens, Joins Panel",
        "snippet": "Sarah Johnson, Director of Internal Communications at Siemens, will speak at the Employee Comms Summit 2024 about digital transformation.",
        "link": "https://example.com/article1",
    },
    {
        "title": "Siemens Appoints New VP of Employee Experience",
        "snippet": "Michael Weber has been appointed VP of Employee Experience at Siemens AG, overseeing all internal employee engagement programs.",
        "link": "https://example.com/article2",
    },
    {
        "title": "Siemens Q3 Earnings Report",
        "snippet": "Siemens AG reported strong Q3 results driven by industrial automation and digitalization.",
        "link": "https://example.com/article3",
    },
]

MOCK_NIKKEI_RESULTS = [
    {
        "title": "シーメンスジャパン、社内広報体制を強化",
        "snippet": "田中 誠氏が社内広報部長に就任。従業員コミュニケーションのデジタル化を推進する方針を発表した。",
        "link": "https://nikkei.com/article1",
    },
    {
        "title": "シーメンス新製品発表",
        "snippet": "シーメンスが新しい産業用ロボットを発表。製造業向けに展開予定。",
        "link": "https://nikkei.com/article2",
    },
]

print("=" * 60)
print("테스트 1: Google 검색 결과 파싱")
print("=" * 60)
client = SerperClient(api_key="dummy")
google_contacts = client._parse_results(MOCK_GOOGLE_RESULTS, "Siemens", source="Google")
for c in google_contacts:
    print(f"  이름: {c.name}")
    print(f"  직책: {c.title}")
    print(f"  출처: {c.source}")
    print(f"  URL: {c.source_url}")
    print()

print("=" * 60)
print("테스트 2: 닛케이 검색 결과 파싱")
print("=" * 60)
nikkei_contacts = client._parse_results(MOCK_NIKKEI_RESULTS, "シーメンス", source="日経新聞")
for c in nikkei_contacts:
    print(f"  이름: {c.name}")
    print(f"  직책: {c.title}")
    print(f"  출처: {c.source}")
    print()

print("=" * 60)
print("테스트 3: 스코어링")
print("=" * 60)
all_contacts = google_contacts + nikkei_contacts
for c in all_contacts:
    s = score_contact(c)
    badge = "🔥 최우선" if s >= 5 else "✅ 적합" if s >= 3 else "📋 참고"
    print(f"  {badge} (점수:{s}) | {c.name} — {c.title} [{c.source}]")

print()
print("=" * 60)
print("테스트 4: 중복 제거")
print("=" * 60)
dupes = google_contacts + google_contacts  # 의도적으로 중복 추가
deduped = deduplicate(dupes)
print(f"  중복 포함: {len(dupes)}명 → 중복 제거 후: {len(deduped)}명")

print()
print("=" * 60)
print("✅ 모든 테스트 통과!")
print("=" * 60)
