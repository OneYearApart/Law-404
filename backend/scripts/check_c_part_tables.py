import json

import psycopg2
from psycopg2.extras import RealDictCursor

DB_URL = "postgresql://edu:1234@localhost:5435/edudb"


def show_table(cur, table_name: str, limit: int = 100):

    print("=" * 78)
    print(f"【테이블: {table_name}】")
    print("=" * 78)

    # 【1】테이블 존재 확인
    cur.execute(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = %s
        )
    """,
        (table_name,),
    )

    exists = cur.fetchone()["exists"]

    if not exists:
        print(f"❌ 테이블이 없습니다: {table_name}")
        print()
        return

    # 【2】컬럼 정보 조회
    # information_schema에서 컬럼명 + 타입을 가져옴
    cur.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = %s
        ORDER BY ordinal_position
    """,
        (table_name,),
    )

    columns = cur.fetchall()

    print("\n【컬럼 구조】")
    for c in columns:
        nullable = "NULL 허용" if c["is_nullable"] == "YES" else "NOT NULL"
        print(f"  {c['column_name']:28s} {c['data_type']:20s} {nullable}")

    # 【3】실제 데이터 조회
    cur.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
    rows = cur.fetchall()

    print(f"\n【데이터】총 {len(rows)}건")
    print("-" * 78)

    for i, row in enumerate(rows, 1):
        print(f"\n[{i}]")
        for k, v in row.items():
            # 긴 값은 잘라서 표시
            val = str(v)
            if len(val) > 60:
                val = val[:60] + "..."
            print(f"    {k:28s} = {val}")

    print()


def main():
    """
    【메인】두 테이블 조회

    확인 목적:
    1. procedure_info  → 절차별 공식 수수료 (expected_cost 프롬프트에 주입할 것)
    2. region_standards → 지역별 소액보증금 기준 (변호사 수수료 계산에 사용)
    """
    print("\n【C파트 메타데이터 테이블 조회】\n")

    try:
        # 【접속】RealDictCursor를 쓰면 결과가 dict로 나와서 읽기 편함
        conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        print(f"✅ DB 접속 성공: {DB_URL}\n")

    except Exception as e:
        print(f"❌ DB 접속 실패: {e}")
        print("\n확인할 것:")
        print("  1. Docker/PostgreSQL이 실행 중인가?")
        print("  2. 포트가 5433이 맞나?")
        return

    # 【조회 1】절차 정보 (수수료)
    show_table(cur, "procedure_info")

    # 【조회 2】지역별 기준
    show_table(cur, "region_standards", limit=20)

    # 【참고】판례 메타데이터도 확인
    # → precedents 섹션에서 court_level, case_year를 쓰려면 필요
    print("=" * 78)
    print("【참고: legal_documents_c의 판례 메타 컬럼】")
    print("=" * 78)

    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'legal_documents_c'
        ORDER BY ordinal_position
    """)

    for c in cur.fetchall():
        print(f"  {c['column_name']:28s} {c['data_type']}")

    cur.close()
    conn.close()

    print("\n✅ 조회 완료")


if __name__ == "__main__":
    main()
