"""
【Phase 3: 성능 평가】결과 분석 및 리포트 생성 (실제 동작 버전)

"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# ════════════════════════════════════════════════════════════════════════════════
# 【Phase3Evaluator 클래스】성능 평가 도구
# ════════════════════════════════════════════════════════════════════════════════


class Phase3Evaluator:
    """
    【Phase 3 성능 평가 클래스】

    ```
    """

    def __init__(self):

        self.results_dir = Path("test_results/phase3")

        self.report_dir = Path("reports")

        self.report_dir.mkdir(exist_ok=True)
        print(f"✅ 리포트 디렉토리 준비: {self.report_dir}")

    def load_results(self) -> Dict[str, Any]:

        print(f"\n【테스트 결과 로드】")
        print(f"경로: {self.results_dir}")

        # 【결과 폴더 확인】
        if not self.results_dir.exists():
            print(f"⚠️  경고: {self.results_dir} 폴더가 없습니다.")
            print(f"   → 먼저 Q1~Q4 테스트를 실행하세요:")
            print(f"   pytest tests/c_part/test_phase3_integration.py -v -s")
            return {}

        # 【JSON 파일 찾기】
        json_files = list(self.results_dir.glob("*.json"))

        if not json_files:
            print(f"⚠️  경고: JSON 파일이 없습니다.")
            print(f"   → 먼저 테스트를 실행해주세요")
            return {}

        print(f"✅ {len(json_files)}개의 테스트 결과 파일 발견")

        # 【모든 JSON 파일 읽기】
        results = {}

        for json_file in json_files:
            try:
                # 【파일 읽기】
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 【카테고리별로 정렬】
                category = data.get("category", "Unknown")

                if category not in results:
                    results[category] = []

                results[category].append(data)

                print(f"  ✓ {category}: {json_file.name}")

            except json.JSONDecodeError:
                print(f"  ❌ 파일 읽기 실패: {json_file.name}")
            except Exception as e:
                print(f"  ❌ 오류: {str(e)}")

        return results

    def generate_report(self, results: Dict[str, Any]) -> str:

        report = []

        # ════════════════════════════════════════════════════════════════════
        # 【헤더】
        # ════════════════════════════════════════════════════════════════════

        report.append("=" * 80)
        report.append("【Phase 3: 실제 GPT API 연결 성능 평가 리포트】")
        report.append("=" * 80)
        report.append(f"\n생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # ════════════════════════════════════════════════════════════════════
        # 【테스트 결과가 없는 경우】
        # ════════════════════════════════════════════════════════════════════

        if not results:
            report.append("⚠️  테스트 결과가 없습니다.\n")
            report.append("【진행 사항】")
            report.append("1. Q1~Q4 테스트 실행:")
            report.append("   pytest tests/c_part/test_phase3_integration.py -v -s")
            report.append("")
            report.append("2. 테스트 완료 후 다시 실행:")
            report.append("   python scripts/evaluate_phase3.py")
            report.append("")
            report.append("=" * 80)
            return "\n".join(report)

        # ════════════════════════════════════════════════════════════════════
        # 【1️⃣ 요약 (Summary)】
        # ════════════════════════════════════════════════════════════════════

        report.append("【1️⃣ 요약】\n")

        # 【전체 통계 계산】
        total_tests = sum(len(tests) for tests in results.values())

        report.append(f"총 테스트 건수: {total_tests}개")
        report.append(f"테스트 카테고리: {len(results)}개")

        # 각 카테고리별 테스트 수
        for category, tests in results.items():
            report.append(f"  - {category}: {len(tests)}개")

        report.append("")

        # ════════════════════════════════════════════════════════════════════
        # 【2️⃣ 상세 결과 (Detailed Results)】
        # ════════════════════════════════════════════════════════════════════

        report.append("【2️⃣ 상세 결과】\n")

        for category, tests in results.items():
            report.append(f"\n{category}")
            report.append("-" * 60)

            if not tests:
                report.append("테스트 결과 없음")
                continue

            # 【최신 결과만 분석】(같은 카테고리의 여러 테스트가 있을 수 있음)
            latest_test = tests[-1]

            report.append(f"질문: {latest_test.get('question', 'N/A')}")
            report.append(f"신뢰도: {latest_test.get('confidence_score', 0):.2f}")
            report.append(f"생성 시간: {latest_test.get('generated_at', 'N/A')}")

            # 【섹션별 정보】
            sections = latest_test.get("sections", {})
            report.append(f"\n섹션별 정보:")

            for section_name, section_info in sections.items():
                content_len = section_info.get("content_length", 0)
                citations = section_info.get("citations_count", 0)

                if content_len > 0:
                    report.append(
                        f"  ✓ {section_name}: {content_len}자 ({citations}개 인용문)"
                    )
                else:
                    report.append(f"  ✗ {section_name}: 생성 안 됨")

            # 【FAQ 정보】
            faq_count = latest_test.get("faq_count", 0)
            report.append(f"FAQ: {faq_count}개")

        report.append("")

        # ════════════════════════════════════════════════════════════════════
        # 【3️⃣ 성능 분석 (Performance Analysis)】
        # ════════════════════════════════════════════════════════════════════

        report.append("【3️⃣ 성능 분석】\n")

        # 【신뢰도 분석】
        all_confidences = [
            test.get("confidence_score", 0)
            for tests in results.values()
            for test in tests
        ]

        if all_confidences:
            avg_confidence = sum(all_confidences) / len(all_confidences)
            min_confidence = min(all_confidences)
            max_confidence = max(all_confidences)

            report.append("신뢰도:")
            report.append(f"  평균: {avg_confidence:.2f}")
            report.append(f"  범위: {min_confidence:.2f} ~ {max_confidence:.2f}")

            # 【신뢰도 레벨 분류】
            high = sum(1 for c in all_confidences if c >= 0.8)
            medium = sum(1 for c in all_confidences if 0.6 <= c < 0.8)
            low = sum(1 for c in all_confidences if c < 0.6)

            report.append(f"  분포: 높음 {high}개 | 중간 {medium}개 | 낮음 {low}개")

        report.append("")

        # ════════════════════════════════════════════════════════════════════
        # 【4️⃣ 섹션 생성 분석】
        # ════════════════════════════════════════════════════════════════════

        report.append("【4️⃣ 섹션 생성 분석】\n")

        section_success = {}

        for tests in results.values():
            if tests:
                latest = tests[-1]
                sections = latest.get("sections", {})

                for section_name, section_info in sections.items():
                    if section_name not in section_success:
                        section_success[section_name] = 0

                    if section_info.get("content_length", 0) > 0:
                        section_success[section_name] += 1

        total_tests = sum(len(tests) for tests in results.values())

        if total_tests > 0:
            for section_name, success_count in section_success.items():
                rate = (success_count / total_tests) * 100
                report.append(
                    f"  {section_name}: {rate:.0f}% ({success_count}/{total_tests})"
                )

        report.append("")

        # ════════════════════════════════════════════════════════════════════
        # 【5️⃣ 결론 (Conclusion)】
        # ════════════════════════════════════════════════════════════════════

        report.append("【5️⃣ 결론】\n")

        if all_confidences:
            if avg_confidence >= 0.75:
                status = "✅ 프로덕션 배포 준비 완료"
            elif avg_confidence >= 0.65:
                status = "⚠️  추가 개선 후 배포 가능"
            else:
                status = "❌ 추가 개선 필요"

            report.append(f"종합 평가: {status}")
        else:
            report.append("평가: 테스트 결과 부족")

        report.append("")
        report.append("=" * 80)

        return "\n".join(report)

    def save_report(self, report_text: str) -> Path:
        print(f"\n【리포트 저장】")

        # 【타임스탐프로 고유한 파일명 생성】
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.report_dir / f"phase3_evaluation_{timestamp}.txt"

        # 【파일로 저장】
        try:
            with open(report_file, "w", encoding="utf-8") as f:
                f.write(report_text)

            print(f"✅ 리포트 저장 성공!")
            print(f"   위치: {report_file}")
            print(f"   크기: {report_file.stat().st_size} bytes")

            return report_file

        except Exception as e:
            print(f"❌ 리포트 저장 실패: {str(e)}")
            return None

    def display_report(self, report_text: str):
        """
        【메서드: 리포트 화면 출력】

        역할:
        - 생성된 리포트를 터미널에 출력
        - 콘솔에서 즉시 확인 가능
        """
        print("\n" + "=" * 80)
        print("【생성된 리포트】")
        print("=" * 80)
        print(report_text)


# ════════════════════════════════════════════════════════════════════════════════
# 【메인 실행】
# ════════════════════════════════════════════════════════════════════════════════


def main():

    print("=" * 80)
    print("【Phase 3: 성능 평가 시작】")
    print("=" * 80)

    # 【Step 1】Evaluator 생성
    print("\n【Step 1】평가기 초기화 중...")
    evaluator = Phase3Evaluator()

    # 【Step 2】테스트 결과 로드
    print("\n【Step 2】테스트 결과 로드 중...")
    results = evaluator.load_results()

    # 【Step 3】리포트 생성
    print("\n【Step 3】리포트 생성 중...")
    report = evaluator.generate_report(results)

    # 【Step 4】리포트 저장
    print("\n【Step 4】리포트 저장 중...")
    saved_file = evaluator.save_report(report)

    # 【Step 5】화면에 출력
    print("\n【Step 5】리포트 출력 중...")
    evaluator.display_report(report)

    # 【완료 메시지】
    print("\n" + "=" * 80)
    print("【평가 완료】✅")
    print("=" * 80)

    if saved_file:
        print(f"\n리포트 파일: {saved_file}")
        print(f"다시 보기: cat {saved_file}")
    else:
        print("\n⚠️  리포트 저장에 실패했습니다.")


if __name__ == "__main__":
    """
    【스크립트 직접 실행】
    
    명령어:
    python scripts/evaluate_phase3.py
    
    이 if __name__ == "__main__": 블록이 실행됩니다.
    """
    main()
