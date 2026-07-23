"""A파트 대표 질문 q01~q20의 확인 슬롯 정의.

슬롯은 후속 대화에서 확인해야 할 사실을 나타낸다.
질문 문장을 바로 저장하는 대신 사실 단위 슬롯을 두면,
이미 확인한 내용은 다시 묻지 않고 남은 사실만 질문할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlotDefinition:
    """상담 중 확인해야 할 사실 하나의 정의."""

    key: str
    label: str
    question: str
    priority: int
    risk_critical: bool = False


@dataclass(frozen=True, slots=True)
class IssueDefinition:
    """대표 질문 하나와 그 질문에서 확인할 슬롯 묶음."""

    issue_id: str
    policy_id: str
    name: str
    description: str
    slots: tuple[SlotDefinition, ...]


def _slot(
    key: str,
    label: str,
    question: str,
    priority: int,
    *,
    risk_critical: bool = False,
) -> SlotDefinition:
    return SlotDefinition(
        key=key,
        label=label,
        question=question,
        priority=priority,
        risk_critical=risk_critical,
    )


ISSUE_DEFINITIONS: dict[str, IssueDefinition] = {
    "q01_owner_proxy": IssueDefinition(
        issue_id="q01_owner_proxy",
        policy_id="owner_proxy",
        name="대리 계약",
        description="소유자 대신 나온 사람의 계약·서명·대금 수령 권한을 확인한다.",
        slots=(
            _slot(
                "registered_owner_identified",
                "등기부 소유자 확인",
                "등기부등본상 실제 소유자는 누구인가요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "owner_proxy_intent_confirmed",
                "소유자의 대리 의사",
                "소유자 본인에게 대리 계약 의사를 직접 확인했나요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "delegation_document_available",
                "위임 자료 보유",
                "위임장이나 대리 권한을 확인할 자료를 받았나요?",
                30,
                risk_critical=True,
            ),
            _slot(
                "delegation_scope_confirmed",
                "위임 범위",
                "위임 자료에 계약 체결 범위가 적혀 있나요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "signature_authority_confirmed",
                "서명 권한",
                "대리인이 계약서에 서명하거나 도장 찍을 권한이 확인됐나요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "payment_authority_confirmed",
                "대금 수령 권한",
                "대리인이나 제3자에게 계약금을 받을 권한이 확인됐나요?",
                60,
                risk_critical=True,
            ),
            _slot(
                "payment_account_holder",
                "계약금 계좌 예금주",
                "계약금을 받을 계좌의 예금주는 누구인가요?",
                70,
                risk_critical=True,
            ),
        ),
    ),
    "q02_co_owner": IssueDefinition(
        issue_id="q02_co_owner",
        policy_id="co_owner",
        name="공동명의 계약",
        description="공동소유자 전원의 계약 의사와 현재 계약자의 권한을 확인한다.",
        slots=(
            _slot(
                "co_owners_identified",
                "공동소유자 전원",
                "등기부등본상 공동소유자는 모두 누구인가요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "ownership_shares_confirmed",
                "공동소유자별 지분",
                "각 공동소유자의 지분을 확인했나요?",
                20,
            ),
            _slot(
                "absent_co_owner_consent",
                "불참 소유자의 동의",
                "계약에 나오지 않은 공동소유자의 동의를 직접 확인했나요?",
                30,
                risk_critical=True,
            ),
            _slot(
                "representative_authority_confirmed",
                "대표자의 대리 권한",
                "현재 계약자가 다른 공동소유자를 대리할 권한이 있나요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "payment_authority_confirmed",
                "대금 수령 권한",
                "계약금을 받을 사람의 수령 권한이 확인됐나요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "payment_account_holder",
                "계약금 계좌 예금주",
                "계약금 계좌 예금주는 누구인가요?",
                60,
                risk_critical=True,
            ),
        ),
    ),
    "q03_owner_lessor_mismatch": IssueDefinition(
        issue_id="q03_owner_lessor_mismatch",
        policy_id="owner_lessor_mismatch",
        name="소유자·임대인 불일치",
        description="등기부 소유자와 계약서 임대인이 다른 이유와 임대 권한을 확인한다.",
        slots=(
            _slot(
                "registry_owner_name",
                "등기부 소유자",
                "등기부등본상 소유자 이름은 무엇인가요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "contract_lessor_name",
                "계약서 임대인",
                "계약서에 적힌 임대인 이름은 무엇인가요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "mismatch_reason_confirmed",
                "불일치 이유",
                "두 사람의 이름이 다른 이유를 확인했나요?",
                30,
                risk_critical=True,
            ),
            _slot(
                "lessor_authority_confirmed",
                "임대 권한",
                "계약서상 임대인의 임대 권한을 확인했나요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "owner_direct_confirmation",
                "소유자 직접 확인",
                "등기부 소유자에게 계약 권한을 직접 확인했나요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "payment_authority_confirmed",
                "대금 수령 권한",
                "계약금 수령 권한을 확인했나요?",
                60,
                risk_critical=True,
            ),
            _slot(
                "payment_account_holder",
                "계약금 계좌 예금주",
                "계약금 계좌의 예금주는 누구인가요?",
                70,
                risk_critical=True,
            ),
        ),
    ),
    "q04_broker_account_payment": IssueDefinition(
        issue_id="q04_broker_account_payment",
        policy_id="account_payment",
        name="제3자 계좌 송금",
        description="소유자 명의가 아닌 계좌의 예금주와 계약금 수령 권한을 확인한다.",
        slots=(
            _slot(
                "registry_owner_identified",
                "등기부 소유자",
                "등기부등본상 실제 소유자는 누구인가요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "contract_counterparty_identified",
                "계약 상대방",
                "실제 계약 상대방은 누구인가요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "payment_account_holder",
                "계좌 예금주",
                "계약금 계좌의 예금주는 누구인가요?",
                30,
                risk_critical=True,
            ),
            _slot(
                "account_holder_relationship",
                "예금주와 소유자의 관계",
                "계좌 예금주와 소유자는 어떤 관계인가요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "payment_authority_confirmed",
                "계약금 수령 권한",
                "해당 계좌의 계약금 수령 권한을 확인했나요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "owner_direct_confirmation",
                "소유자 직접 확인",
                "소유자 본인에게 해당 계좌로 보내도 되는지 직접 확인했나요?",
                60,
                risk_critical=True,
            ),
        ),
    ),
    "q05_account_change_before_contract": IssueDefinition(
        issue_id="q05_account_change_before_contract",
        policy_id="account_change",
        name="계약 직전 계좌 변경",
        description="계좌 변경 요청의 진위와 새 예금주의 수령 권한을 확인한다.",
        slots=(
            _slot(
                "original_account_holder",
                "기존 계좌 예금주",
                "기존에 안내받은 계좌의 예금주는 누구였나요?",
                10,
            ),
            _slot(
                "changed_account_holder",
                "변경 계좌 예금주",
                "새로 안내받은 계좌의 예금주는 누구인가요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "change_requester_identified",
                "변경 요청자",
                "누가 계좌 변경을 요청했나요?",
                30,
                risk_critical=True,
            ),
            _slot(
                "owner_change_intent_confirmed",
                "소유자의 변경 의사",
                "소유자 본인에게 계좌 변경 사실을 직접 확인했나요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "account_change_reason",
                "계좌 변경 이유",
                "계좌가 변경된 이유는 무엇인가요?",
                50,
            ),
            _slot(
                "new_account_payment_authority",
                "새 계좌 수령 권한",
                "새 계좌 예금주의 계약금 수령 권한을 확인했나요?",
                60,
                risk_critical=True,
            ),
            _slot(
                "written_change_record",
                "변경 기록",
                "계좌 변경 내용이 문자나 확인서로 남아 있나요?",
                70,
                risk_critical=True,
            ),
        ),
    ),
    "q06_broker_explanation_mismatch": IssueDefinition(
        issue_id="q06_broker_explanation_mismatch",
        policy_id="broker_document_mismatch",
        name="확인설명서·계약서 불일치",
        description="두 문서의 불일치 항목과 정정 여부를 확인한다.",
        slots=(
            _slot(
                "mismatched_fields_identified",
                "불일치 항목",
                "두 문서에서 어떤 항목이 다르게 적혀 있나요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "correct_value_confirmed",
                "정확한 내용",
                "어느 문서의 내용이 정확한지 확인했나요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "broker_explanation_received",
                "중개사 설명",
                "공인중개사에게 불일치 이유를 설명받았나요?",
                30,
            ),
            _slot(
                "lessor_explanation_received",
                "임대인 설명",
                "임대인에게 불일치 이유를 확인했나요?",
                40,
            ),
            _slot(
                "corrected_contract_received",
                "정정 계약서",
                "정정된 계약서를 다시 받았나요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "corrected_explanation_document_received",
                "정정 확인설명서",
                "정정된 중개대상물 확인설명서를 받았나요?",
                60,
                risk_critical=True,
            ),
        ),
    ),
    "q07_mortgage": IssueDefinition(
        issue_id="q07_mortgage",
        policy_id="mortgage",
        name="근저당 확인",
        description="근저당과 보증금·주택가액·선순위 권리를 함께 확인한다.",
        slots=(
            _slot(
                "mortgage_exists",
                "근저당 존재",
                "등기부등본에 현재 유효한 근저당이 있나요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "maximum_secured_amount",
                "채권최고액",
                "등기부에 적힌 채권최고액은 얼마인가요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "actual_debt_amount",
                "실제 채무액",
                "현재 실제 대출 잔액을 확인할 수 있나요?",
                30,
            ),
            _slot(
                "deposit_amount",
                "전세보증금",
                "계약할 전세보증금은 얼마인가요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "property_value",
                "주택가액",
                "최근 주택가액을 어떤 자료로 확인했나요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "other_prior_rights",
                "다른 선순위 권리",
                "근저당 외에 다른 선순위 권리가 있나요?",
                60,
                risk_critical=True,
            ),
            _slot(
                "latest_registry_checked",
                "최신 등기부 확인",
                "계약 직전에 최신 등기부등본을 다시 확인했나요?",
                70,
                risk_critical=True,
            ),
        ),
    ),
    "q08_multiunit_priority": IssueDefinition(
        issue_id="q08_multiunit_priority",
        policy_id="multiunit_priority",
        name="다가구 선순위 보증금",
        description="다가구 전체 선순위 보증금과 권리관계·주택가액을 확인한다.",
        slots=(
            _slot(
                "building_type_confirmed",
                "다가구 여부",
                "해당 주택이 다가구주택인지 확인했나요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "total_senior_deposits",
                "선순위 보증금 총액",
                "다른 세대의 선순위 보증금 총액을 확인했나요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "mortgage_and_prior_rights",
                "근저당·선순위 권리",
                "근저당과 다른 선순위 권리를 확인했나요?",
                30,
                risk_critical=True,
            ),
            _slot(
                "deposit_amount",
                "내 보증금",
                "계약할 보증금은 얼마인가요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "property_value",
                "주택가액",
                "주택가액은 얼마이며 어떤 자료로 확인했나요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "household_status_checked",
                "전입세대 현황",
                "기존 전입세대와 점유 상태를 확인했나요?",
                60,
            ),
            _slot(
                "data_source_date",
                "확인 자료 기준일",
                "선순위 보증금 자료는 언제 기준인가요?",
                70,
            ),
        ),
    ),
    "q09_registry_restriction_warning": IssueDefinition(
        issue_id="q09_registry_restriction_warning",
        policy_id="registry_restriction",
        name="압류·가압류 등 권리 제한",
        description="권리 제한의 종류와 현재 유효 여부·말소 여부를 확인한다.",
        slots=(
            _slot(
                "restriction_type",
                "권리 제한 종류",
                "등기부에 어떤 권리 제한이 적혀 있나요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "restriction_active",
                "현재 유효 여부",
                "그 권리 제한이 현재 유효한 상태인가요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "cancellation_status",
                "말소 여부",
                "말소 표시나 말소 접수 내역이 있나요?",
                30,
                risk_critical=True,
            ),
            _slot(
                "registration_date",
                "접수·등기 일자",
                "권리 제한의 접수일이나 등기일은 언제인가요?",
                40,
            ),
            _slot(
                "creditor_or_right_holder",
                "권리자",
                "권리자 또는 채권자는 누구인가요?",
                50,
            ),
            _slot(
                "impact_explained",
                "계약 영향 설명",
                "공인중개사나 전문가에게 계약에 미치는 영향을 설명받았나요?",
                60,
            ),
            _slot(
                "latest_registry_checked",
                "최신 등기부 확인",
                "계약 직전에 최신 등기부등본을 다시 확인했나요?",
                70,
                risk_critical=True,
            ),
        ),
    ),
    "q10_trust": IssueDefinition(
        issue_id="q10_trust",
        policy_id="trust_registry",
        name="신탁등기",
        description="수탁자와 신탁원부상 임대 권한·동의 조건을 확인한다.",
        slots=(
            _slot(
                "trust_registration_exists",
                "신탁등기 존재",
                "등기부등본에 신탁등기가 있나요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "trustee_identified",
                "수탁자",
                "등기부상 수탁자는 누구인가요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "trust_ledger_checked",
                "신탁원부 확인",
                "신탁원부를 발급받아 확인했나요?",
                30,
                risk_critical=True,
            ),
            _slot(
                "lessor_authority_confirmed",
                "임대 권한",
                "계약 상대방의 임대 권한이 신탁원부에서 확인되나요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "trustee_consent_required",
                "수탁자 동의 필요 여부",
                "임대차계약에 수탁자 동의가 필요한가요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "trustee_consent_confirmed",
                "수탁자 동의",
                "필요한 경우 수탁자의 동의를 확인했나요?",
                60,
                risk_critical=True,
            ),
            _slot(
                "payment_account_holder",
                "대금 계좌 예금주",
                "계약금 계좌의 예금주는 누구인가요?",
                70,
                risk_critical=True,
            ),
        ),
    ),
    "q11_opposability_move_in": IssueDefinition(
        issue_id="q11_opposability_move_in",
        policy_id="opposability",
        name="대항력 발생 시점",
        description="주택 인도와 전입신고 완료 시점을 확인한다.",
        slots=(
            _slot(
                "possession_completed",
                "주택 인도",
                "실제로 주택을 인도받아 입주했나요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "move_in_report_completed",
                "전입신고",
                "전입신고를 완료했나요?",
                20,
                risk_critical=True,
            ),
            _slot("possession_date", "입주일", "실제 입주한 날짜는 언제인가요?", 30),
            _slot(
                "move_in_report_date",
                "전입신고일",
                "전입신고를 접수한 날짜는 언제인가요?",
                40,
            ),
        ),
    ),
    "q12_fixed_date_priority": IssueDefinition(
        issue_id="q12_fixed_date_priority",
        policy_id="fixed_date_priority",
        name="확정일자와 우선변제권",
        description="확정일자와 함께 대항요건을 갖췄는지 확인한다.",
        slots=(
            _slot(
                "possession_completed",
                "주택 인도",
                "실제로 주택을 인도받아 입주했나요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "move_in_report_completed",
                "전입신고",
                "전입신고를 완료했나요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "fixed_date_received",
                "확정일자",
                "계약서에 확정일자를 받았나요?",
                30,
                risk_critical=True,
            ),
            _slot("possession_date", "입주일", "실제 입주일은 언제인가요?", 40),
            _slot("move_in_report_date", "전입신고일", "전입신고일은 언제인가요?", 50),
            _slot(
                "fixed_date_date",
                "확정일자 부여일",
                "확정일자를 받은 날짜는 언제인가요?",
                60,
            ),
        ),
    ),
    "q13_owner_change": IssueDefinition(
        issue_id="q13_owner_change",
        policy_id="owner_change",
        name="계약 후 소유자 변경",
        description="새 소유자와 대항요건·보증금 반환 관계를 확인한다.",
        slots=(
            _slot(
                "ownership_change_confirmed",
                "소유권 변경",
                "최신 등기부등본에서 소유권 변경을 확인했나요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "new_owner_identified",
                "새 소유자",
                "새 소유자는 누구인가요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "transfer_registration_date",
                "소유권 이전일",
                "소유권 이전 등기일은 언제인가요?",
                30,
            ),
            _slot(
                "possession_completed",
                "주택 인도",
                "현재 실제로 입주해 있나요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "move_in_report_completed",
                "전입신고",
                "전입신고를 완료한 상태인가요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "opposability_effective",
                "대항력 요건",
                "소유권 변경 전에 대항요건을 갖췄는지 확인했나요?",
                60,
                risk_critical=True,
            ),
            _slot(
                "deposit_return_party_confirmed",
                "보증금 반환 상대방",
                "현재 보증금 반환 의무가 누구에게 있는지 확인했나요?",
                70,
            ),
        ),
    ),
    "q14_special_clause_deposit_return": IssueDefinition(
        issue_id="q14_special_clause_deposit_return",
        policy_id="special_clause_return",
        name="계약금 반환 특약",
        description="특약의 발동 조건·반환 범위·기한·방법을 확인한다.",
        slots=(
            _slot(
                "special_clause_text",
                "특약 원문",
                "계약금 반환 특약의 정확한 문구는 무엇인가요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "trigger_condition",
                "발동 조건",
                "어떤 상황에서 반환 특약이 적용되나요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "return_scope",
                "반환 범위",
                "계약금 전액인지 일부인지 반환 범위가 적혀 있나요?",
                30,
                risk_critical=True,
            ),
            _slot(
                "return_deadline",
                "반환 기한",
                "계약금을 언제까지 반환하는지 적혀 있나요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "return_method", "반환 방법", "반환 방법과 계좌가 정해져 있나요?", 50
            ),
            _slot(
                "proof_requirement",
                "증빙 조건",
                "특약 적용을 위해 필요한 증빙이 정해져 있나요?",
                60,
            ),
            _slot(
                "parties_agreed",
                "당사자 합의",
                "임대인과 임차인이 해당 특약에 서명하거나 합의했나요?",
                70,
                risk_critical=True,
            ),
        ),
    ),
    "q15_after_contract_procedure": IssueDefinition(
        issue_id="q15_after_contract_procedure",
        policy_id="after_contract_procedure",
        name="계약 직후 절차",
        description="계약서·지급 기록 보관과 잔금·입주 전 절차를 확인한다.",
        slots=(
            _slot(
                "signed_contract_original_kept",
                "계약서 원본 보관",
                "서명·날인된 계약서 원본을 보관하고 있나요?",
                10,
            ),
            _slot(
                "payment_record_kept",
                "계약금 지급 기록",
                "계약금 이체 내역이나 영수증을 보관하고 있나요?",
                20,
            ),
            _slot("balance_date", "잔금일", "잔금일은 언제인가요?", 30),
            _slot("move_in_date", "입주 예정일", "실제 입주 예정일은 언제인가요?", 40),
            _slot(
                "latest_registry_recheck_planned",
                "잔금 전 등기부 재확인",
                "잔금 전에 최신 등기부등본을 다시 확인할 예정인가요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "lease_report_status",
                "임대차신고",
                "이 계약의 임대차신고는 어떻게 처리했나요?",
                60,
            ),
            _slot(
                "move_in_report_plan",
                "전입신고 계획",
                "입주일에 전입신고할 계획이 있나요?",
                70,
            ),
            _slot(
                "fixed_date_plan",
                "확정일자 계획",
                "확정일자를 받을 시점을 정했나요?",
                80,
            ),
        ),
    ),
    "q16_lease_report": IssueDefinition(
        issue_id="q16_lease_report",
        policy_id="lease_report",
        name="주택 임대차신고",
        description="계약 조건으로 신고 대상·기한·완료 여부를 확인한다.",
        slots=(
            _slot(
                "contract_address", "계약 주소", "계약한 주택의 주소는 어디인가요?", 10
            ),
            _slot(
                "contract_date",
                "계약 체결일",
                "계약을 체결한 날짜는 언제인가요?",
                20,
                risk_critical=True,
            ),
            _slot("deposit_amount", "보증금", "보증금은 얼마인가요?", 30),
            _slot("monthly_rent", "월세", "월세가 있다면 얼마인가요?", 40),
            _slot(
                "contract_change_type",
                "신규·갱신 여부",
                "신규 계약인가요, 갱신 계약인가요?",
                50,
            ),
            _slot(
                "reporting_required_confirmed",
                "신고 대상 여부",
                "공식 시스템이나 주민센터에서 신고 대상인지 확인했나요?",
                60,
                risk_critical=True,
            ),
            _slot(
                "reporting_completed",
                "신고 완료",
                "신고 대상이라면 임대차신고를 완료했나요?",
                70,
            ),
            _slot(
                "report_receipt_kept",
                "신고필증 보관",
                "신고필증이나 접수 결과를 보관하고 있나요?",
                80,
            ),
        ),
    ),
    "q17_household_certificate": IssueDefinition(
        issue_id="q17_household_certificate",
        policy_id="household_certificate",
        name="전입세대확인서 확인 시점",
        description="계약 전과 잔금 전의 전입세대·점유 변동을 확인한다.",
        slots=(
            _slot(
                "pre_contract_certificate_checked",
                "계약 전 확인",
                "계약 전에 전입세대확인서를 확인했나요?",
                10,
            ),
            _slot(
                "existing_households_status",
                "기존 전입세대",
                "기존 전입세대나 점유자가 확인됐나요?",
                20,
                risk_critical=True,
            ),
            _slot("balance_date", "잔금일", "잔금일은 언제인가요?", 30),
            _slot(
                "pre_balance_recheck_planned",
                "잔금 전 재확인",
                "잔금 전에 전입세대확인서를 다시 확인할 예정인가요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "latest_registry_checked",
                "최신 등기부 확인",
                "최신 등기부등본도 함께 확인했나요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "senior_deposit_info_checked",
                "선순위 보증금",
                "선순위 임차보증금 관련 자료를 확인했나요?",
                60,
                risk_critical=True,
            ),
        ),
    ),
    "q18_address_mismatch": IssueDefinition(
        issue_id="q18_address_mismatch",
        policy_id="address_mismatch",
        name="계약서·등기부 주소 불일치",
        description="주소 구성 요소를 비교해 같은 목적물인지 확인한다.",
        slots=(
            _slot(
                "contract_address",
                "계약서 주소",
                "계약서에 적힌 주소는 무엇인가요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "registry_address",
                "등기부 주소",
                "등기부등본에 적힌 주소는 무엇인가요?",
                20,
                risk_critical=True,
            ),
            _slot(
                "mismatched_address_component",
                "불일치 부분",
                "지번·도로명·건물명·동·호수 중 무엇이 다른가요?",
                30,
                risk_critical=True,
            ),
            _slot(
                "same_property_confirmed",
                "동일 목적물 확인",
                "두 주소가 실제로 같은 주택을 가리키는지 확인했나요?",
                40,
                risk_critical=True,
            ),
            _slot(
                "building_register_checked",
                "건축물대장 확인",
                "건축물대장이나 현장 표시와 대조했나요?",
                50,
            ),
            _slot(
                "corrected_contract_received",
                "정정 계약서",
                "주소가 잘못됐다면 정정된 계약서를 받았나요?",
                60,
                risk_critical=True,
            ),
        ),
    ),
    "q19_deposit_transfer_mismatch": IssueDefinition(
        issue_id="q19_deposit_transfer_mismatch",
        policy_id="deposit_transfer_mismatch",
        name="계약서 금액·이체 내역 불일치",
        description="계약 금액과 실제 지급액·수령인·차액 원인을 확인한다.",
        slots=(
            _slot(
                "contract_total_deposit",
                "계약서 보증금",
                "계약서상 총보증금은 얼마인가요?",
                10,
                risk_critical=True,
            ),
            _slot(
                "contract_payment_schedule",
                "계약서 지급 일정",
                "계약금·중도금·잔금 일정은 어떻게 적혀 있나요?",
                20,
            ),
            _slot(
                "transferred_total",
                "현재 이체 합계",
                "현재까지 실제로 이체한 금액의 합계는 얼마인가요?",
                30,
                risk_critical=True,
            ),
            _slot("transfer_dates", "이체 일자", "각 금액을 언제 이체했나요?", 40),
            _slot(
                "receiving_account_holders",
                "수령 계좌 예금주",
                "각 이체 계좌의 예금주는 누구인가요?",
                50,
                risk_critical=True,
            ),
            _slot(
                "difference_amount",
                "차액",
                "계약서 금액과 이체 합계의 차액은 얼마인가요?",
                60,
                risk_critical=True,
            ),
            _slot(
                "difference_reason",
                "차액 원인",
                "차액이 발생한 이유를 확인했나요?",
                70,
                risk_critical=True,
            ),
            _slot(
                "settlement_confirmation_received",
                "정산 확인",
                "임대인과 차액·남은 잔금을 서면으로 확인했나요?",
                80,
                risk_critical=True,
            ),
        ),
    ),
    "q20_guarantee_check": IssueDefinition(
        issue_id="q20_guarantee_check",
        policy_id="guarantee_precheck",
        name="전세보증금반환보증 검토",
        description="보증기관·상품·계약 조건·신청 시점·제출 서류를 확인한다.",
        slots=(
            _slot(
                "guarantee_provider",
                "보증기관",
                "어느 보증기관의 반환보증을 검토하고 있나요?",
                10,
            ),
            _slot(
                "guarantee_product",
                "보증 상품",
                "신청하려는 보증 상품 이름은 무엇인가요?",
                20,
            ),
            _slot(
                "contract_start_date", "계약 시작일", "계약 시작일은 언제인가요?", 30
            ),
            _slot("contract_end_date", "계약 종료일", "계약 종료일은 언제인가요?", 40),
            _slot("deposit_amount", "전세보증금", "전세보증금은 얼마인가요?", 50),
            _slot(
                "housing_type",
                "주택 유형",
                "아파트·연립·다가구 등 주택 유형은 무엇인가요?",
                60,
            ),
            _slot(
                "application_deadline_checked",
                "신청 가능 기간",
                "공식 상품안내에서 신청 가능 기간을 확인했나요?",
                70,
                risk_critical=True,
            ),
            _slot(
                "registry_checked",
                "권리관계 확인",
                "최신 등기부등본의 소유자와 권리관계를 확인했나요?",
                80,
                risk_critical=True,
            ),
            _slot(
                "payment_proof_available",
                "보증금 지급 증빙",
                "보증금 지급 내역이나 영수증을 준비했나요?",
                90,
            ),
            _slot(
                "required_documents_checked",
                "제출 서류 확인",
                "보증기관의 최신 제출 서류 목록을 확인했나요?",
                100,
            ),
        ),
    ),
}


def get_issue_definition(issue_id: str) -> IssueDefinition:
    """issue_id에 해당하는 정의를 반환하고 없으면 명확한 오류를 낸다."""

    try:
        return ISSUE_DEFINITIONS[issue_id]
    except KeyError as exc:
        raise ValueError(f"지원하지 않는 A파트 issue_id입니다: {issue_id}") from exc


def get_supported_issue_ids() -> tuple[str, ...]:
    """q01~q20 지원 ID를 정의 순서대로 반환한다."""

    return tuple(ISSUE_DEFINITIONS)
