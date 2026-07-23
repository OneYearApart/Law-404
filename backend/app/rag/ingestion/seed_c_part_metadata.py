"""
================================================================================
【Python 스크립트】판례 메타데이터 DB 업데이트

파일명: seed_c_part_metadata.py
위치: backend/app/rag/ingestion/

================================================================================
"""

import json
import os
from datetime import datetime

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

# 【.env 파일 로드】
load_dotenv()

# ════════════════════════════════════════════════════════════════════════════════
# 📋 설정 (Configurations)
# ════════════════════════════════════════════════════════════════════════════════

# 【DATABASE_URL】
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://edu:1234@localhost:5435/edudb")

# 【JSON 파일 경로】
JSON_FILE = "data_collection_c/data/precedents_selected_카테고리3.json"

# ════════════════════════════════════════════════════════════════════════════════
# 🔖 판례별 메타데이터 정의
# ════════════════════════════════════════════════════════════════════════════════

# 【공식 데이터만】
# 각 판례의 사건번호를 키로 해서, "공식" 메타데이터만 저장합니다.
#
# 포함된 것:
# • court_level: 대법원/고등법원 (법원 체계)
# • case_year: 판례 연도 (판례에서 나옴)
# • ruling_type: 승소/패소 (판례에서 나옴)
# • appeal_outcome: 상소 결과 (판례에서 나옴)

PRECEDENT_METADATA = {
    # 【판례 #1】2023다202228
    "2023다202228": {
        "court_level": 0,  # 대법원
        "case_year": 2024,
        "ruling_type": "임차인 승소",
        "appeal_outcome": "상소 없음",
    },
    # 【판례 #2】2024다321973
    "2024다321973": {
        "court_level": 0,  # 대법원
        "case_year": 2025,
        "ruling_type": "임차인 승소",
        "appeal_outcome": "상소 없음",
    },
    # 【판례 #3】2024다326398
    "2024다326398": {
        "court_level": 0,  # 대법원
        "case_year": 2024,
        "ruling_type": "임차인 승소",
        "appeal_outcome": "상소 없음",
    },
    # 【판례 #4】2025다210305
    "2025다210305": {
        "court_level": 0,  # 대법원
        "case_year": 2025,
        "ruling_type": "임차인 승소",
        "appeal_outcome": "상소 없음",
    },
    # 【판례 #5】2022다246610, 246627
    "2022다246610, 246627": {
        "court_level": 0,
        "case_year": 2023,
        "ruling_type": "임차인 승소",
        "appeal_outcome": "상소 없음",
    },
}

# 【관련 절차】
# 이 판례와 관련된 절차들을 JSON으로 저장합니다.

RELATED_PROCEDURES = {
    "procedures": [
        {"name": "임차권등기명령", "order": 1},
        {"name": "소액사건", "order": 2},
        {"name": "일반소송", "order": 3},
    ]
}


# ════════════════════════════════════════════════════════════════════════════════
# 🔧 클래스: PrecedentMetadataUpdater
# ════════════════════════════════════════════════════════════════════════════════


class PrecedentMetadataUpdater:
    """
    【이 클래스가 하는 일】

    판례 메타데이터를 JSON 파일에서 읽어서 PostgreSQL DB에 저장하는 역할입니다.

    메서드 구조:
    • __init__(): DB 연결 정보 초기화
    • connect(): DB와의 연결 시작
    • disconnect(): DB 연결 종료
    • load_json_data(): JSON 파일 읽기
    • update_precedent(): 개별 판례 메타데이터 업데이트
    • run(): 전체 프로세스 실행
    • _verify_updates(): 업데이트 검증
    """

    def __init__(self, database_url: str):
        """
        【초기화 메서드】

        인자:
        - database_url: PostgreSQL 연결 문자열
        """
        self.database_url = database_url
        self.conn = None  # 아직 연결 안 함
        self.updated_count = 0  # 성공 카운트
        self.failed_count = 0  # 실패 카운트

    def connect(self):
        """
        【DB 연결 메서드】

        PostgreSQL에 연결합니다.
        """
        try:
            self.conn = psycopg2.connect(self.database_url)
            print("✓ PostgreSQL 연결 성공")
        except Exception as e:
            print(f"❌ DB 연결 실패: {e}")
            raise  # 에러를 위로 던져서 프로그램을 멈춤

    def disconnect(self):
        """
        【DB 연결 종료 메서드】

        연결을 정리합니다.
        """
        if self.conn:
            self.conn.close()
            print("✓ DB 연결 종료")

    def load_json_data(self, filepath: str) -> dict:
        """
        【JSON 파일 로드 메서드】

        인자:
        - filepath: JSON 파일 경로 (예: "data_collection_c/data/precedents_selected_카테고리3.json")
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:  # UTF-8: 한글 지원
                data = json.load(f)
            print(f"✓ JSON 파일 로드 완료: {filepath}")
            return data
        except FileNotFoundError:
            print(f"❌ 파일을 찾을 수 없습니다: {filepath}")
            raise

    def update_precedent(self, case_number: str, metadata: dict):
        """
        【개별 판례 메타데이터 업데이트 메서드】

        인자:
        - case_number: 사건번호 (예: "2023다202228")
        - metadata: 메타데이터 딕셔너리 (court_level, case_year 등)

        """
        try:
            cursor = self.conn.cursor()

            # 【related_procedures를 JSON 문자열로 변환】
            related_procedures = json.dumps(
                RELATED_PROCEDURES, ensure_ascii=False, indent=2
            )

            # 【SQL UPDATE 쿼리 - 공식 데이터만】
            sql = """
                UPDATE legal_documents_c
                SET
                    court_level = %s,
                    case_year = %s,
                    ruling_type = %s,
                    appeal_outcome = %s,
                    related_procedures = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE case_number = %s
            """

            cursor.execute(
                sql,
                (
                    metadata["court_level"],
                    metadata["case_year"],
                    metadata["ruling_type"],
                    metadata["appeal_outcome"],
                    related_procedures,
                    case_number,
                ),
            )

            if cursor.rowcount > 0:
                print(f"  ✓ {case_number}: 업데이트 완료 ({cursor.rowcount}행)")
                self.updated_count += 1  # 성공 카운트 증가
            else:
                print(
                    f"  ⚠️  {case_number}: 해당 행을 찾을 수 없음 (사건번호가 없거나 오류인가?)"
                )
                self.failed_count += 1

            self.conn.commit()
            cursor.close()

        except Exception as e:
            print(f"  ❌ {case_number}: 업데이트 실패 - {e}")
            self.failed_count += 1
            # 【롤백】이 판례의 업데이트가 실패해도 다른 판례는 계속 진행
            self.conn.rollback()

    def run(self, json_filepath: str):
        """
        【전체 프로세스 실행 메서드】

        순서:
        1. JSON 파일 로드
        2. DB 연결
        3. 각 판례의 메타데이터 업데이트
        4. 업데이트 결과 검증
        5. DB 연결 종료
        """
        try:
            # 1. JSON 파일 로드
            json_data = self.load_json_data(json_filepath)

            # 2. DB 연결
            self.connect()

            # 3. 각 질문별 판례 처리
            print("\n【판례 메타데이터 업데이트】\n")

            for question_id, precedents in json_data.items():
                print(f"\n[{question_id}] 판례 처리 중...")

                # 각 질문마다 여러 판례가 있음
                for precedent in precedents:
                    case_number = precedent.get("사건번호")  # JSON에서 사건번호 추출

                    # PRECEDENT_METADATA에서 이 사건번호의 메타데이터를 찾음
                    if case_number in PRECEDENT_METADATA:
                        metadata = PRECEDENT_METADATA[case_number]
                        self.update_precedent(case_number, metadata)
                    else:
                        # 메타데이터를 정의하지 않은 판례는 건너뜀
                        print(
                            f"  ⚠️  {case_number}: 메타데이터 정의 없음 (PRECEDENT_METADATA에 추가하세요)"
                        )
                        self.failed_count += 1

            # 4. 결과 출력
            print(f"\n【업데이트 완료】")
            print(f"  성공: {self.updated_count}건")
            print(f"  실패: {self.failed_count}건")

            # 5. 업데이트된 데이터 검증
            self._verify_updates()

        finally:
            # 무조건 DB 연결 종료 (에러 나도, 안 나도)
            self.disconnect()

    def _verify_updates(self):
        """
        【검증 메서드】

        업데이트가 제대로 되었는지 확인합니다.
        """
        try:
            cursor = self.conn.cursor()

            # 【SQL 쿼리 - 공식 데이터만 조회】
            cursor.execute("""
                SELECT 
                    case_number,
                    court_level,
                    case_year,
                    ruling_type,
                    appeal_outcome
                FROM legal_documents_c
                WHERE source_type = 'precedent' AND category_tag = 3
                ORDER BY case_year DESC
            """)

            rows = cursor.fetchall()

            print("\n【DB 검증】")
            print(f"\n업데이트된 판례 {len(rows)}건:\n")

            # 가독성 좋게 출력 (공식 데이터만)
            for row in rows:
                case_number, court_level, case_year, ruling_type, appeal_outcome = row
                # court_level을 문자로 변환
                court_name = "대법원" if court_level == 0 else "고등법원"

                print(f"  • {case_number} ({case_year}년, {court_name})")
                print(f"    - 판결: {ruling_type}")
                print(f"    - 상소: {appeal_outcome}")

            cursor.close()
            self.conn.commit()

        except Exception as e:
            print(f"❌ 검증 실패: {e}")


# ════════════════════════════════════════════════════════════════════════════════
# 🚀 메인 함수
# ════════════════════════════════════════════════════════════════════════════════


def main():
    """
    【스크립트의 진입점】

    """
    print("=" * 70)
    print("카테고리 3 판례 메타데이터 업데이트")
    print("=" * 70)

    updater = PrecedentMetadataUpdater(DATABASE_URL)
    updater.run(JSON_FILE)

    print("\n✅ 작업 완료!")


# ════════════════════════════════════════════════════════════════════════════════
# 【if __name__ == "__main__":】
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
